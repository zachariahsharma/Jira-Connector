### Imports

from jira import JIRA, Project
from jira.resources import Attachment
import os
from dotenv import load_dotenv
import boto3
import time
import requests


load_dotenv()


### Environemnt Variables
JIRA_USERNAME = os.getenv("JIRA_USERNAME")
JIRA_PASSWORD = os.getenv("JIRA_PASSWORD")
JIRA_SERVER = os.getenv("JIRA_SERVER")
AUTOCAM_APIKEY = os.getenv("AUTOCAM_APIKEY")


### JIRA Setup
jira = JIRA(
    server=JIRA_SERVER,
    basic_auth=(JIRA_USERNAME, JIRA_PASSWORD),
)

### AutoCAM Setup
session = requests.Session()
session.headers.update({"Authorization": f"Bearer {AUTOCAM_APIKEY}"})


### Helper Functions
def getJiraIssues():
    issues = jira.search_issues(
        'project = Hardware AND assignee = Empty AND status = "Ready to Fabricate"  and Machinery = "CNC Router"'
    )
    return issues


def handleS3withIssue(issues, Name):
    s3 = boto3.resource("s3")
    bucket = s3.Bucket("autocam-attachments")
    attachments = issues.get_field("attachment")
    if not attachments:
        return
    for attachment in attachments:
        if attachment.filename.endswith(".step"):
            Key = f"Valor-{Name}-{attachment.filename}"
            if not any(obj.key == Key for obj in bucket.objects.all()):
                bucket.put_object(Key=Key, Body=attachment.get())
            break


def handlePostgresPartCategories(Material, Thickness):
    response = session.get("http://localhost:3000/api/pc")
    part_categories = response.json()
    for pc in part_categories:
        if pc["material"] == Material and pc["thickness"] == Thickness:
            return pc["id"]
    response = session.post(
        "http://localhost:3000/api/pc",
        json={"material": Material, "thickness": Thickness},
    )
    category_id = response.json().get("id")
    return category_id


def handlePostgresParts(Name, Epic, Ticket, Quantity, category_id):
    parts = session.get(f"http://localhost:3000/api/pc/{category_id}/parts").json()
    for part in parts:
        if part["ticket"] == Ticket:
            return
    session.post(
        f"http://localhost:3000/api/pc/{category_id}/parts",
        json={
            "name": Name,
            "epic": Epic,
            "ticket": Ticket,
            "quantity": Quantity,
        },
    )


def cleanUpOldParts(issue_keys: set[str]):
    if not issue_keys:
        print("No JIRA issues returned; skipping cleanup to avoid deleting everything.")
        return
    deleted_parts = []
    for pc in session.get("http://localhost:3000/api/pc").json():
        parts = session.get(f"http://localhost:3000/api/pc/{pc['id']}/parts").json()
        for part in parts:
            if part["ticket"] not in issue_keys:
                deleted_parts.append(part)
                session.delete(f"http://localhost:3000/api/parts/{part['id']}")
        if len(parts) == 0:
            session.delete(f"http://localhost:3000/api/pc/{pc['id']}")

    s3 = boto3.resource("s3")
    bucket = s3.Bucket("autocam-attachments")
    for obj in bucket.objects.all():
        key = obj.key
        if not key.startswith("Valor-"):
            continue

        rest = key[len("Valor-") :]
        if "-" not in rest:
            continue
        part_name, _filename = rest.rsplit("-", 1)

        for part in deleted_parts:
            if part["name"] == part_name:
                obj.delete()


### Main Function
def processJiraIssues():
    issues = getJiraIssues()
    issue_keys = {issue.key for issue in issues}

    print("issues found:", len(issues))

    processed = 0
    for issue in issues:
        Epic = jira.issue(issue.get_field("customfield_10110")).get_field("summary")
        Name = issue.get_field("summary")
        Quantity = int(issue.get_field("customfield_10206"))
        Ticket = issue.key
        Material = str(issue.get_field("customfield_10202"))
        Thickness = float(str(issue.get_field("customfield_10207")))

        if (
            not Material
            or not Thickness
            or not Name
            or not Epic
            or not Quantity
            or Material == ""
            or Thickness == 0
            or Name == ""
            or Epic == ""
            or Quantity == 0
        ):
            continue

        handleS3withIssue(issue, Name)
        category_id = handlePostgresPartCategories(Material, Thickness)
        handlePostgresParts(Name, Epic, Ticket, Quantity, category_id)
        processed += 1

    print(f"Finished processing issues. {processed} processed.")
    cleanUpOldParts(issue_keys)


if __name__ == "__main__":
    while True:
        processJiraIssues()
        time.sleep(60)
