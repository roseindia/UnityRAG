import json


def test_smoke_search_and_chat(tenants, client):
    a = tenants["A"]
    r = client.post("/api/v1/search", headers=a["analyst"], json={"query": "flood damage basement exclusion"})
    assert r.status_code == 200, r.text
    top = r.json()["results"][0]
    print(json.dumps({k: top[k] for k in ("title", "section_path", "score", "explanation", "highlight")}, default=str, indent=1))
    c = client.post("/api/v1/chat", headers=a["analyst"], json={"message": "Is flood damage to a vehicle parked in a basement covered?"})
    assert c.status_code == 200, c.text
    body = c.json()
    print(json.dumps({k: body[k] for k in ("answer", "status", "evidence_strength", "warnings", "diagnostics", "rewritten_query")}, indent=1, default=str))
    print([ (x["marker"], x["title"], x["section_path"], x["verified"]) for x in body["citations"]])
