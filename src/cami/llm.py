from cami.errors import ResourceError


def require_optional_llm() -> None:
    raise ResourceError("M6 is not implemented or enabled. It requires a separate frozen protocol, explicit API model, key and paid-request budget.")
