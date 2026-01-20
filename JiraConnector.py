### Imports

from jira import JIRA
import os
from dotenv import load_dotenv
import time
import requests
import json


load_dotenv()


### Environemnt Variables
JIRA_USERNAME = os.getenv("JIRA_USERNAME")
JIRA_PASSWORD = os.getenv("JIRA_PASSWORD")
JIRA_SERVER = os.getenv("JIRA_SERVER")
AUTOCAM_APIKEY = os.getenv("AUTOCAM_APIKEY")
BASE_URL = os.getenv("AUTOCAM_BASEURL")


### JIRA Setup
jira = JIRA(
    server=JIRA_SERVER,
    basic_auth=(JIRA_USERNAME, JIRA_PASSWORD),
)

### AutoCAM Setup
session = requests.Session()
session.headers.update({"Authorization": f"Bearer {AUTOCAM_APIKEY}"})
teamid = None
EMPTY_JIRA_PASS_THRESHOLD = 2
consecutive_empty_jira_passes = 0

### Helper Functions


def safe_positive_int(value):
    try:
        if value is None or value == "":
            return None
        number = int(value)
        return number if number > 0 else None
    except (ValueError, TypeError):
        return None


def safe_positive_float(value):
    try:
        if value is None or value == "":
            return None
        number = float(value)
        return number if number > 0 else None
    except (ValueError, TypeError):
        return None


def safe_json_response(response, context=""):
    """Return parsed JSON or None if the response is not usable."""
    if response is None:
        return None
    try:
        response.raise_for_status()
    except requests.exceptions.RequestException as exc:
        status = getattr(response, "status_code", "unknown")
        message = f"{context} failed with status {status}: {exc}" if context else str(exc)
        print(message)
        body = getattr(response, "text", "")
        if body:
            print(f"Response body (truncated): {body[:500]}")
        return None
    try:
        return response.json()
    except ValueError:
        snippet = response.text[:500] if hasattr(response, "text") else ""
        print(f"{context} returned non-JSON response: {snippet}")
        return None


def getTeamID():
    print("Base URL: ", BASE_URL)
    try:
        response = session.get(f"{BASE_URL}/api/teams")
    except requests.exceptions.RequestException as exc:
        raise Exception("Could not reach AutoCAM API for team ID") from exc
    data = safe_json_response(response, "Fetch AutoCAM team ID")
    if not data:
        raise Exception("AutoCAM API returned no data for team ID")
    target = data[0] if isinstance(data, list) and data else data
    teamid = target.get("id") if isinstance(target, dict) else None
    if not teamid:
        raise Exception("Could not fetch team ID from AutoCAM API")
    return teamid


def getJiraIssues():
    issues = jira.search_issues(
        'project = Hardware AND assignee = Empty AND status = "Ready to Fabricate"  and Machinery = "CNC Router"'
    )
    return issues


def handlePostgresPartCategories(Material, Thickness):
    part_category = {"material": Material, "thickness": Thickness}
    response = session.get(f"{BASE_URL}/api/pc", params=part_category)
    pc = safe_json_response(response, "Fetch part categories") or []
    for category in pc:
        if not isinstance(category, dict):
            continue
        if (
            category.get("material") == Material
            and category.get("thickness") == Thickness
        ):
            return category.get("id")
    response = session.post(f"{BASE_URL}/api/pc", json=part_category)
    created = safe_json_response(response, "Create part category")
    if created and isinstance(created, dict):
        return created.get("id")
    return None


def handlePostgresParts(Name, Epic, Ticket, Quantity, category_id, attachment):
    parts_response = session.get(f"{BASE_URL}/api/pc/{category_id}/parts")
    parts = safe_json_response(
        parts_response, f"Fetch parts for category {category_id}"
    )
    if parts is None:
        parts = []
    for part in parts:
        if part.get("ticket") == Ticket:
            return
    response = session.post(
        f"{BASE_URL}/api/pc/{category_id}/parts",
        files={
            "data": (
                None,
                json.dumps(
                    {
                        "name": Name,
                        "epic": Epic,
                        "ticket": Ticket,
                        "quantity": Quantity,
                    }
                ),
                "application/json",
            ),
            "file": (attachment.filename, attachment.get(), "application/octet-stream"),
        },
    )
    created = safe_json_response(response, f"Create part for ticket {Ticket}")
    if created is None:
        print(
            "Data sent:",
            {
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
    response = session.get(f"{BASE_URL}/api/pc")
    categories = safe_json_response(response, "Fetch part categories for cleanup")
    if categories is None:
        return
    if not isinstance(categories, list):
        categories = []
    for pc in categories:
        category_id = pc.get("id") if isinstance(pc, dict) else None
        if not category_id:
            continue
        parts_response = session.get(f"{BASE_URL}/api/pc/{category_id}/parts")
        parts = safe_json_response(
            parts_response, f"Fetch parts for category {category_id}"
        )
        if parts is None:
            continue
        if not isinstance(parts, list):
            parts = []
        for part in parts:
            if part.get("ticket") not in issue_keys:
                deleted_parts.append(part)
                session.delete(f"{BASE_URL}/api/parts/{part['id']}")
        if len(parts) == 0:
            session.delete(f"{BASE_URL}/api/pc/{category_id}")


def cleanUpOldBoxTubes(issue_keys: set[str]):
    if not issue_keys:
        print(
            "No JIRA issues returned; skipping box tube cleanup to avoid deleting everything."
        )
        return
    response = session.get(f"{BASE_URL}/api/boxTubes")
    box_tubes = safe_json_response(response, "Fetch box tubes for cleanup")
    if box_tubes is None:
        return
    if not isinstance(box_tubes, list):
        box_tubes = []
    for tube in box_tubes:
        if tube.get("ticket") not in issue_keys:
            tube_id = tube.get("id")
            if not tube_id:
                continue
            delete_response = session.delete(f"{BASE_URL}/api/boxTubes/{tube_id}")
            if not delete_response.ok:
                print(
                    f"Failed to delete box tube {tube_id}: {delete_response.status_code}, {delete_response.text}"
                )


def deleteAllPartsAndCategories():
    print(
        "No JIRA issues for two consecutive passes; deleting all AutoCAM parts, categories, and box tubes."
    )
    try:
        box_tube_response = session.get(f"{BASE_URL}/api/boxTubes")
    except requests.exceptions.RequestException as exc:
        print(f"Failed to fetch box tubes for deletion: {exc}")
    else:
        box_tubes = safe_json_response(
            box_tube_response, "Fetch box tubes for deletion"
        )
        if box_tubes is None:
            return
        if not isinstance(box_tubes, list):
            box_tubes = []
        for tube in box_tubes:
            tube_id = tube.get("id")
            if not tube_id:
                continue
            delete_response = session.delete(f"{BASE_URL}/api/boxTubes/{tube_id}")
            if not delete_response.ok:
                print(
                    f"Failed to delete box tube {tube_id}: {delete_response.status_code}, {delete_response.text}"
                )
    try:
        response = session.get(f"{BASE_URL}/api/pc")
    except requests.exceptions.RequestException as exc:
        print(f"Failed to fetch part categories for deletion: {exc}")
        return
    categories = safe_json_response(response, "Fetch part categories for deletion")
    if categories is None:
        return
    if not isinstance(categories, list):
        categories = []
    for category in categories:
        category_id = category.get("id")
        if not category_id:
            continue
        try:
            parts_response = session.get(f"{BASE_URL}/api/pc/{category_id}/parts")
        except requests.exceptions.RequestException as exc:
            print(f"Failed to fetch parts for category {category_id}: {exc}")
            continue
        parts = safe_json_response(
            parts_response, f"Fetch parts for category {category_id} during deletion"
        )
        if parts is None:
            continue
        if not isinstance(parts, list):
            parts = []
        for part in parts:
            part_id = part.get("id")
            if not part_id:
                continue
            delete_response = session.delete(f"{BASE_URL}/api/parts/{part_id}")
            if not delete_response.ok:
                print(
                    f"Failed to delete part {part_id}: {delete_response.status_code}, {delete_response.text}"
                )
        delete_response = session.delete(f"{BASE_URL}/api/pc/{category_id}")
        if not delete_response.ok:
            print(
                f"Failed to delete category {category_id}: {delete_response.status_code}, {delete_response.text}"
            )


def cleanUpOldDrafts(issue_keys: set[str], drafts, issue_prefixes: set[str]):
    if not issue_keys or not drafts or not issue_prefixes:
        return
    for draft in drafts:
        ticket = draft.get("ticket")
        if not ticket or ticket in issue_keys:
            continue
        prefix = ticket.split("-")[0] if "-" in ticket else None
        if prefix and prefix in issue_prefixes:
            deleteDraft(draft["id"])


def handleBoxTubes(Name, Epic, Ticket, Quantity, teamid=teamid, attachment=None):
    boxtubes_response = session.get(f"{BASE_URL}/api/boxTubes")
    boxtubes = safe_json_response(boxtubes_response, "Fetch box tubes")
    if boxtubes is None:
        boxtubes = []
    if not isinstance(boxtubes, list):
        boxtubes = []
    for boxtube in boxtubes:
        if boxtube.get("ticket") == Ticket:
            return
    response = session.post(
        f"{BASE_URL}/api/boxTubes",
        files={
            "data": (
                None,
                json.dumps(
                    {
                        "name": Name,
                        "epic": Epic,
                        "ticket": Ticket,
                        "quantity": Quantity,
                        "teamid": teamid,
                    }
                ),
                "application/json",
            ),
            "file": (attachment.filename, attachment.get(), "application/octet-stream"),
        },
    )
    if not response.ok:
        print(
            f"Failed to create box/tube. Status: {response.status_code}, Response: {response.text}"
        )
    return response


def fetchTeamDrafts(team_id):
    if not team_id:
        return [], {}, {}
    try:
        response = session.get(f"{BASE_URL}/api/drafts")
    except requests.exceptions.RequestException as exc:
        print(f"Failed to fetch drafts: {exc}")
        return [], {}, {}
    drafts = safe_json_response(response, "Fetch drafts")
    if drafts is None:
        return [], {}, {}
    if not isinstance(drafts, list):
        print("Fetch drafts returned unexpected payload; ignoring.")
        return [], {}, {}
    drafts_by_ticket_type = {}
    drafts_by_ticket = {}
    for draft in drafts:
        ticket = draft.get("ticket")
        draft_type = draft.get("type")
        if ticket and draft_type:
            drafts_by_ticket_type[(ticket, draft_type)] = draft
            drafts_by_ticket.setdefault(ticket, []).append(draft)
    return drafts, drafts_by_ticket_type, drafts_by_ticket


def findDraftForTicket(ticket, draft_type, drafts_by_ticket_type, drafts_by_ticket):
    if not ticket:
        return None
    draft = drafts_by_ticket_type.get((ticket, draft_type))
    if draft:
        return draft
    possible = drafts_by_ticket.get(ticket, [])
    if possible:
        return possible[0]
    return None


def createDraft(team_id, draft_type, data, attachment=None):
    if not team_id:
        return None
    payload = {k: v for k, v in data.items() if v is not None}
    payload["type"] = draft_type
    files = {
        "data": (None, json.dumps(payload), "application/json"),
    }
    if attachment:
        files["file"] = (
            attachment.filename,
            attachment.get(),
            "application/octet-stream",
        )
    response = session.post(f"{BASE_URL}/api/drafts", files=files)
    draft = safe_json_response(response, f"Create draft for {data.get('ticket')}")
    if not draft or not isinstance(draft, dict):
        return None
    draft_id = draft.get("id")
    if not draft_id:
        print(f"Draft created for {data.get('ticket')} but ID missing in response.")
        return None
    return draft_id


def updateDraftMetadata(draft_id, data):
    if not data:
        return True
    response = session.patch(f"{BASE_URL}/api/drafts/{draft_id}", json=data)
    if not response.ok:
        print(
            f"Failed to update draft {draft_id}: {response.status_code}, {response.text}"
        )
        return False
    return True


def updateDraftFile(draft_id, attachment):
    if not attachment:
        return True
    files = {
        "file": (
            attachment.filename,
            attachment.get(),
            "application/octet-stream",
        )
    }
    response = session.patch(f"{BASE_URL}/api/drafts/{draft_id}/file", files=files)
    if not response.ok:
        print(
            f"Failed to upload file for draft {draft_id}: {response.status_code}, {response.text}"
        )
        return False
    return True


def deleteDraft(draft_id):
    response = session.delete(f"{BASE_URL}/api/drafts/{draft_id}")
    if not response.ok:
        print(
            f"Failed to delete draft {draft_id}: {response.status_code}, {response.text}"
        )
        return False
    return True


def finalizeDraft(draft_id):
    response = session.post(f"{BASE_URL}/api/drafts/{draft_id}/finalize")
    if not response.ok:
        print(
            f"Failed to finalize draft {draft_id}: {response.status_code}, {response.text}"
        )
        return False
    return True


### Main Function
def processJiraIssues():
    global consecutive_empty_jira_passes
    issues = getJiraIssues()
    issue_count = len(issues)
    issue_keys = {issue.key for issue in issues}
    issue_prefixes = {key.split("-")[0] for key in issue_keys if "-" in key}
    drafts, drafts_by_ticket_type, drafts_by_ticket = fetchTeamDrafts(teamid)

    if issue_count == 0:
        consecutive_empty_jira_passes += 1
        print(
            f"No JIRA issues found. Empty pass count: {consecutive_empty_jira_passes}"
        )
    else:
        consecutive_empty_jira_passes = 0

    print("issues found:", issue_count)

    processed = 0
    for issue in issues:
        Ticket = issue.key
        attachments = issue.get_field("attachment") or []
        attachments = [att for att in attachments if att.filename.endswith(".step")]
        attachment = attachments[0] if attachments else None

        Name = issue.get_field("summary")
        if isinstance(Name, str):
            Name = Name.strip()

        Epic = None
        epic_link = issue.get_field("customfield_10110")
        if epic_link:
            try:
                epic_summary = jira.issue(epic_link).get_field("summary")
                Epic = str(epic_summary).strip() if epic_summary else None
            except Exception as e:
                print(f"Unable to fetch epic for {Ticket}: {e}")

        Quantity = safe_positive_int(issue.get_field("customfield_10206"))
        Material = issue.get_field("customfield_10202")
        if Material:
            Material = str(Material).strip()
            if Material == "":
                Material = None
        Thickness = safe_positive_float(str(issue.get_field("customfield_10207")))
        draft_type = "box_tube" if Name and "tube" in Name.lower() else "part"
        existing_draft = findDraftForTicket(
            Ticket, draft_type, drafts_by_ticket_type, drafts_by_ticket
        )
        if existing_draft and existing_draft.get("type") != draft_type:
            print(
                f"Draft {existing_draft.get('id')} type mismatch for {Ticket}; recreating."
            )
            if deleteDraft(existing_draft.get("id")):
                existing_draft = None

        draft_metadata = {
            "name": Name,
            "epic": Epic,
            "ticket": Ticket,
            "quantity": Quantity,
        }
        if draft_type == "part":
            draft_metadata["pending_category"] = (
                {"material": Material, "thickness": Thickness}
                if Material and Thickness
                else None
            )

        has_attachment = attachment is not None
        common_complete = (
            bool(Name)
            and bool(Epic)
            and bool(Ticket)
            and Quantity is not None
            and has_attachment
        )
        if draft_type == "part":
            is_complete = common_complete and bool(Material) and Thickness is not None
        else:
            is_complete = common_complete
        print(
            f"Processing {Ticket}: complete={is_complete} Material={Material} Thickness={Thickness}"
        )
        if not is_complete:
            if existing_draft:
                updateDraftMetadata(existing_draft["id"], draft_metadata)
                if attachment:
                    needs_file = (
                        not existing_draft.get("has_file")
                        or existing_draft.get("file_name") != attachment.filename
                    )
                    if needs_file and updateDraftFile(existing_draft["id"], attachment):
                        existing_draft["has_file"] = True
                        existing_draft["file_name"] = attachment.filename
            else:
                createDraft(teamid, draft_type, draft_metadata, attachment)
            continue

        if existing_draft:
            metadata_updated = updateDraftMetadata(existing_draft["id"], draft_metadata)
            if not metadata_updated:
                continue
            needs_file = attachment and (
                not existing_draft.get("has_file")
                or existing_draft.get("file_name") != attachment.filename
            )
            if needs_file and not updateDraftFile(existing_draft["id"], attachment):
                continue
            if finalizeDraft(existing_draft["id"]):
                processed += 1
                drafts_by_ticket_type.pop((Ticket, draft_type), None)
            continue

        if draft_type == "box_tube":
            handleBoxTubes(Name, Epic, Ticket, Quantity, teamid, attachment)
            processed += 1
            continue

        category_id = handlePostgresPartCategories(Material, Thickness)
        if category_id:
            handlePostgresParts(Name, Epic, Ticket, Quantity, category_id, attachment)
            processed += 1

    print(f"Finished processing issues. {processed} processed.")
    cleanUpOldParts(issue_keys)
    cleanUpOldBoxTubes(issue_keys)
    cleanUpOldDrafts(issue_keys, drafts, issue_prefixes)
    if issue_count == 0 and consecutive_empty_jira_passes >= EMPTY_JIRA_PASS_THRESHOLD:
        deleteAllPartsAndCategories()
        consecutive_empty_jira_passes = 0


if __name__ == "__main__":
    teamid = getTeamID()
    while True:
        processJiraIssues()
        time.sleep(60)
