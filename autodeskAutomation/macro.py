### Imports

import selenium
from selenium import webdriver
import selenium.webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
import selenium.webdriver.remote
import selenium.webdriver.remote.webelement
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
import pymongo
import time
from bs4 import BeautifulSoup as bs
import subprocess
import json
import requests
from threading import Thread
from selenium.webdriver.common.action_chains import ActionChains

import os

os.environ["DISPLAY"] = ":1"


### Global

options = webdriver.ChromeOptions()
options.add_argument("--headless=new")
options.add_argument("--auto-open-devtools-for-tabs")
driver = webdriver.Chrome(options=options)
# driver = None
client = pymongo.MongoClient(
    "mongodb://127.0.0.1:27017/?directConnection=true&serverSelectionTimeoutMS=2000&appName=mongosh+2.4.2"
)
db = client["jira"]
tasks = db["tasks"]
imported = db["imported"]

### Functions


def element_containing(
    value=None,
    id=None,
    className=None,
    specificType="*",
    driver: webdriver.Chrome = driver,
) -> selenium.webdriver.remote.webelement.WebElement:
    if value:
        return driver.find_element(
            By.XPATH, f'//{specificType}[contains(text(), "{value}")]'
        )
    elif id:
        return driver.find_element(By.XPATH, f'//{specificType}[contains(@id, "{id}")]')
    elif className:
        return driver.find_element(By.XPATH, f'//{specificType}[@class="{className}"]')


def element_containing_complex(value=None, id=None, className=None):
    if value:
        WebDriverWait(driver, 60).until(
            EC.visibility_of_element_located(
                (By.XPATH, f'//*[contains(text(), "{value}")]')
            )
        )
        return driver.find_element(By.XPATH, f'//*[contains(text(), "{value}")]')
    elif id:
        WebDriverWait(driver, 60).until(
            EC.visibility_of_element_located((By.XPATH, f'//*[contains(@id, "{id}")]'))
        )
        return driver.find_element(By.XPATH, f'//*[contains(@id, "{id}")]')
    elif className:
        WebDriverWait(driver, 60).until(
            EC.visibility_of_element_located(
                (By.XPATH, f'//*[contains(@class, "{className}")]')
            )
        )
        return driver.find_element(By.XPATH, f'//*[@class="{className}"]')


def login_to_jira(driver=driver):
    while True:
        try:
            driver.get("https://jira.valor6800.com/secure/Dashboard.jspa")
            time.sleep(0.5)
            if element_containing(id="login", driver=driver):
                element_containing(id="login-form-username", driver=driver).send_keys(
                    "Sharma"
                )
                element_containing(id="login-form-password", driver=driver).send_keys(
                    "6922568729Za!" + Keys.ENTER
                )
            time.sleep(1)
            break
        except:
            time.sleep(2)


def list_issues_from_jira():
    driver.get(
        "https://jira.valor6800.com/browse/HAR-972?jql=project%20%3D%20Hardware%20AND%20assignee%20%3D%20Empty%20AND%20status%20%3D%20%22Ready%20to%20Fabricate%22%20%20and%20Machinery%20%3D%20%22CNC%20Router%22"
    )
    element_containing(value="Search", specificType="button").click()
    time.sleep(1)
    ol = element_containing_complex(className="issue-list")
    soup = bs(ol.get_attribute("innerHTML"), "html.parser")
    children = [child["data-key"] for child in soup.find_all(recursive=False)]
    cookies = driver.get_cookies()
    s = requests.Session()
    for cookie in cookies:
        s.cookies.set(cookie["name"], cookie["value"])
    for child in children:
        if imported.find_one({"child": child}):
            continue
        driver.get("https://jira.valor6800.com" + f"/browse/{child}")
        print("https://jira.valor6800.com" + f"/browse/{child}")
        time.sleep(2)
        attachmentsList = element_containing(className="item-attachments")
        try:
            quantity_elem = driver.find_element(
                By.XPATH,
                '//label[contains(text(),"Qty:")]/parent::strong/following-sibling::div',
            )
            quantity = driver.execute_script(
                "return arguments[0].firstChild.nodeValue.trim();", quantity_elem
            )
            thickness_elem = driver.find_element(
                By.XPATH,
                '//label[contains(text(),"Thickness")]/parent::strong/following-sibling::div',
            )
            thickness = driver.execute_script(
                "return arguments[0].firstChild.nodeValue.trim();", thickness_elem
            )
            material_elem = driver.find_element(
                By.XPATH,
                '//label[contains(text(),"Material")]/parent::strong/following-sibling::div',
            )
            material = driver.execute_script(
                "return arguments[0].firstChild.nodeValue.trim();", material_elem
            )

        except:
            print(child, " has insufficient details")
            continue
        imported.insert_one({"child": child, "quantity": quantity})
        if not tasks.find_one(
            {
                "Material": material,
                "Thickness": float(thickness),
                "Status": "Not Started",
            }
        ):
            tasks.insert_one(
                {
                    "Material": material,
                    "Thickness": float(thickness),
                    "Parts": [],
                    "Status": "pending",
                    "name": material + " " + thickness,
                }
            )
        tasks.update_one(
            {
                "Material": material,
                "Thickness": float(thickness),
                "Status": "Not Started",
            },
            {"$push": {"Parts": child}},
        )
        soup = bs(attachmentsList.get_attribute("innerHTML"), "html.parser")
        attachments = soup.find_all("a", class_="attachment-title")
        print(f"Downloading attachments for {child}", len(attachments))
        for attachment in list(set(attachments)):
            url = "https://jira.valor6800.com" + attachment["href"]
            print("Downloading from", url)
            local_filename = os.path.join(
                os.path.expanduser("~/Documents/old/nest2dapi/imported"),
                child + ".step",
            )
            r = s.get(url, stream=True)
            print(r.status_code)
            if r.status_code == 200:
                with open(local_filename, "wb") as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)


def createCamTicket(name, material, thickness):
    pass
    # createTicket = webdriver.Chrome(options=options)
    # login_to_jira(createTicket)
    # createTicket.get("https://jira.valor6800.com/secure/CreateIssue!default.jspa")
    # time.sleep(1)
    # element_containing(
    #     id="issue-create-submit", specificType="input", driver=createTicket
    # ).click()
    # time.sleep(1)
    # element_containing(
    #     id="summary", specificType="input", driver=createTicket
    # ).send_keys(name)
    # element_containing(
    #     id="customfield_10110-field", specificType="input", driver=createTicket
    # ).send_keys("CAM")
    # time.sleep(0.2)
    # element_containing(
    #     id="customfield_10110-field", specificType="input", driver=createTicket
    # ).send_keys(Keys.ARROW_DOWN)
    # time.sleep(0.2)
    # element_containing(
    #     id="customfield_10110-field", specificType="input", driver=createTicket
    # ).send_keys(Keys.ARROW_DOWN)
    # time.sleep(0.2)
    # element_containing(
    #     id="customfield_10110-field", specificType="input", driver=createTicket
    # ).send_keys(Keys.RETURN)
    # element_containing(
    #     id="priority-field", specificType="input", driver=createTicket
    # ).send_keys("High")
    # element_containing(
    #     id="issue-create-submit", specificType="input", driver=createTicket
    # ).click()
    # time.sleep(1)
    # element_containing(
    #     id="opsbar-transitions_more", specificType="a", driver=createTicket
    # ).click()
    # time.sleep(1)
    # createTicket.find_element(
    #     By.XPATH,
    #     "//*[text()='Ready to Fabricate' and contains(@class, 'workflow-cell')]/../..",
    # ).click()
    # name = createTicket.current_url.split("/")[-1]
    # time.sleep(2)
    # createTicket.close()
    # tasks.update_one(
    #     {"Material": material, "Thickness": float(thickness), "Status": "Not Started"},
    #     {"$set": {"Status": "pending"}},
    # )
    # tasks.update_one(
    #     {"Material": material, "Thickness": float(thickness), "Status": "pending"},
    #     {"$set": {"name": name}},
    # )


### Async Functions


def importNewFiles():
    login_to_jira()
    while True:
        try:
            list_issues_from_jira()
            time.sleep(60)
        except Exception as e:
            print(e)
            login_to_jira()


def taskMaintainance():
    taskDriver = webdriver.Chrome(options=options)
    print("task maintainance started")
    login_to_jira(taskDriver)
    tasks = db["tasks"]
    while True:
        try:
            for task in tasks.find():
                name = task["name"]
                match task["Status"]:
                    case "pending":
                        print("pending")
                        taskDriver.get(f"https://jira.valor6800.com/browse/{name}")
                        elements = taskDriver.find_elements(
                            By.XPATH, '//*[contains(@id, "comment-")]'
                        )
                        for element in elements:
                            if "done" in element.get_attribute("innerHTML"):
                                tasks.update_one(
                                    {"name": name}, {"$set": {"height": 48}}
                                )
                                tasks.update_one(
                                    {"name": name}, {"$set": {"width": 24}}
                                )
                                tasks.update_one(
                                    {"name": name}, {"$set": {"depth": 0.245}}
                                )
                                tasks.update_one(
                                    {"name": name}, {"$set": {"machine": "Swift"}}
                                )
                                tasks.update_one(
                                    {"name": name}, {"$set": {"comments": 1}}
                                )
                                tasks.update_one(
                                    {"name": name}, {"$set": {"Status": "primed"}}
                                )
                                break
                    case "cammed":
                        taskDriver.get(f"https://jira.valor6800.com/browse/{name}")
                        time.sleep(1)
                        file_input = taskDriver.find_element(
                            By.XPATH, '//input[@type="file"]'
                        )
                        baseDir = os.path.dirname(os.path.realpath(__file__))
                        files = []
                        for file in os.listdir(f"FinishedCAM/{name}"):
                            files.append(
                                os.path.realpath(
                                    os.path.join(
                                        baseDir, f"../FinishedCAM/{name}/{file}"
                                    )
                                )
                            )
                        file_input.send_keys("\n".join(files))
                        tasks.update_one({"name": name}, {"$set": {"Status": "done"}})
                        time.sleep(2)
                    case "done":
                        taskDriver.get(f"https://jira.valor6800.com/browse/{name}")
                        commentCounter = 0
                        elements = taskDriver.find_elements(
                            By.XPATH, '//*[contains(@id, "comment-")]'
                        )
                        for element in elements:
                            if "done" in element.get_attribute("innerHTML"):
                                commentCounter += 1
                        if commentCounter > task["comments"]:
                            file_input = taskDriver.find_element(
                                By.XPATH, '//input[@type="file"]'
                            )
                            print(
                                len(
                                    taskDriver.find_elements(
                                        By.XPATH, '//a[contains(@id, "del_")]'
                                    )
                                )
                            )
                            while (
                                len(
                                    taskDriver.find_elements(
                                        By.XPATH, '//a[contains(@id, "del_")]'
                                    )
                                )
                                > 0
                            ):
                                element = taskDriver.find_element(
                                    By.XPATH, '//a[contains(@id, "del_")]'
                                )
                                actions = ActionChains(taskDriver)
                                actions.move_to_element(element).perform()
                                element.click()
                                time.sleep(1)
                                element_containing(
                                    id="delete-attachment-submit",
                                    specificType="input",
                                    driver=taskDriver,
                                ).click()
                                time.sleep(2)
                            tasks.update_one({"name": name}, {"$set": {"height": 48}})
                            tasks.update_one({"name": name}, {"$set": {"width": 24}})
                            tasks.update_one({"name": name}, {"$set": {"depth": 0.245}})
                            tasks.update_one(
                                {"name": name}, {"$set": {"machine": "Swift"}}
                            )
                            tasks.update_one(
                                {"name": name},
                                {"$set": {"comments": task["comments"] + 1}},
                            )
                            tasks.update_one(
                                {"name": name}, {"$set": {"Status": "primed"}}
                            )
                            os.rmdir(f"FinishedCAM/{name}")
            time.sleep(60)
        except Exception as e:
            print(e)
            login_to_jira(taskDriver)


def main():
    Thread(target=taskMaintainance, args=()).start()
    importNewFiles()


### Run


if __name__ == "__main__":
    main()
