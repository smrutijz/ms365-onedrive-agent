# Example usage
from src.clients.oneDriveHelper import GraphClient
from src.utils.token_manager import TokenManager

# access_token = TokenManager().refresh_access_token()
access_token = TokenManager().get_access_token()


client = GraphClient(access_token)
content = client.download_file("9509D56FD07A9FEF!sf91afd7de5784802b367fea1537400ee")
res=client.get_item("9509D56FD07A9FEF!sf91afd7de5784802b367fea1537400ee")
name = res.get("name")
mimetype = res.get("file").get("mimeType") if res.get("file") else None




content = b'test'
name="test.txt"
mimetype="text/plain"
type(content)

import requests
import time

BASE = "https://wap-apac-smrutiaisolution-docling-b3heeeadera9apa7.eastasia-01.azurewebsites.net"




import requests

files = [('files', open('requirements.txt', 'rb'))]

res = requests.post("http://localhost:5001/process-file", files=files)
print(res.json())





import requests

BASE = "http://localhost:5001/v1/convert/file"

# Fake file content
fake_file = b"test"

files = [("example", fake_file)]

data = {
    "target_type": "inbody",
    "from_formats": "md",
    "to_formats": "md"
}

resp = requests.post(
    BASE,
    files=[fake_file],
    data=data
)

print(resp.status_code)
print(resp.json())
resp.text
resp.raise_for_status()

task = resp.json()
task_id = task["task_id"]
print("Task ID:", task_id)
requests.get(f"{BASE}/v1/convert/file/result/{task_id}")





import requests

BASE = "https://wap-apac-smrutiaisolution-docling-b3heeeadera9apa7.eastasia-01.azurewebsites.net"

fake_file = b"test"

files = {
    "files": ("example.txt", fake_file, "text/plain")
}

data = {
    "from_formats": "md",
    "to_formats": "md",
    "target_type": "inbody"
}

# Step 1: submit async job
resp = requests.post(
    f"{BASE}/v1/convert/file/async",
    files=files,
    data=data
)

task = resp.json()
task_id = task["task_id"]
print("Task ID:", task_id)
requests.get(f"{BASE}/v1/convert/file/result/{task_id}")

# Step 2: poll result
import time
while True:
    r = requests.get(f"{BASE}/v1/convert/file/result/{task_id}")
    if r.status_code == 200:
        print("DONE:", r.json())
        break
    print("Waiting...")
    time.sleep(1)






def convert_file_async(file_bytes, filename, mimetype):
    # files = [("files", (filename, file_bytes, mimetype))]
    # data = [("to_formats", "json"), ("to_formats", "md")]
    # resp = requests.post(f"{BASE}/v1/convert/file/async", files=files, data=data)
    resp = requests.post(f"{BASE}/v1/convert/file/async", json=content)
    resp.raise_for_status()
    return resp.json()["task_id"]

def poll_and_fetch(task_id, timeout=60, interval=2):
    url = f"{BASE}/v1/status/poll/{task_id}"
    start = time.time()
    while True:
        r = requests.get(url)
        r.raise_for_status()
        stat = r.json().get("task_status")
        print("Status:", stat)
        if stat in ("success", "failure"):
            break
        if time.time() - start > timeout:
            raise TimeoutError("Task did not complete in time")
        time.sleep(interval)

    # Now try fetching result
    res = requests.get(f"{BASE}/v1/result/{task_id}")
    if res.status_code == 200:
        return res.json()
    else:
        print("No result stored (404 or other):", res.status_code, res.text)
        return None


def fetch_result(task_id):
    r = requests.get(f"{BASE}/v1/result/{task_id}")
    r.raise_for_status()
    return r.json()

# Example usage
task = convert_file_async(b"test", "test.txt", "text/plain")
status = poll_and_fetch(task)
if status == "success":
    result = fetch_result(task)
    print(result["document"]["json_content"])
    print(result["document"]["md_content"])
else:
    print("Conversion failed", task)


import requests

BASE = "https://wap-apac-smrutiaisolution-docling-b3heeeadera9apa7.eastasia-01.azurewebsites.net"

def convert_file_sync(file_bytes, filename, mimetype):
    files = [
        ("files", (filename, file_bytes, mimetype))
    ]
    data = [
        ("to_formats", "json"),
        ("to_formats", "md"),
        # Optionally specify from_formats if necessary
        # e.g., for text: ("from_formats", "text")
    ]

    resp = requests.post(f"{BASE}/v1/convert/file", files=files, data=data)
    print("HTTP:", resp.status_code)
    print("BODY:", resp.text)  # helpful for debugging

    resp.raise_for_status()
    result = resp.json()

    json_content = result["document"].get("json_content")
    md_content   = result["document"].get("md_content")

    return json_content, md_content

# Test with PDF bytes from OneDrive
json_out, md_out = convert_file_sync(content, name, mimetype)
print("JSON output:", json_out)
print("Markdown output:", md_out)
