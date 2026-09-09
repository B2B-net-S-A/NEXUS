"""Exercise ordinary rule writes with the editor's read-before-write revision."""


async def rule_request(client, method, url, **kwargs):
    if "/cv-rule" in url and (
        method in {"PUT", "DELETE"} or url.endswith("/confirm") or "/copy-from/" in url
    ):
        resource = url.split("/cv-rule", 1)[0] + "/cv-rule"
        current = await client.get(resource, headers=kwargs.get("headers"))
        revision = (
            current.json().get("edit_revision", 0) if current.status_code == 200 else 0
        )
        if method == "PUT":
            kwargs["json"] = {**kwargs.get("json", {}), "expected_revision": revision}
        else:
            kwargs["params"] = {
                **kwargs.get("params", {}),
                "expected_revision": revision,
            }
    return await client.request(method, url, **kwargs)
