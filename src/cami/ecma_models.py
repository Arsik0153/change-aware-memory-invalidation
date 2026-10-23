"""Versioned compiler-analysis values, independent of research and product records."""

from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

RelativePath = Annotated[str, StringConstraints(min_length=1, max_length=4096)]
Digest = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
RelationKind = Literal["imports", "reexports", "calls", "uses"]


def captured_path(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 4096
        or "\\" in value
        or ":" in value
        or any(ord(c) < 32 for c in value)
        or any(p in ("", ".", "..", "node_modules") for p in value.split("/"))
    ):
        raise ValueError(f"Expected canonical captured relative path: {value!r}")
    return value


class EcmaValue(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, serialize_by_alias=True)


class EvidenceSite(EcmaValue):
    path: RelativePath
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    line: int = Field(ge=1)
    column: int = Field(ge=1)
    end_line: int = Field(ge=1)
    end_column: int = Field(ge=1)

    @model_validator(mode="after")
    def ordered(self) -> Self:
        captured_path(self.path)
        if self.end < self.start:
            raise ValueError("Reversed evidence span")
        return self


class EcmaSymbolKey(EcmaValue):
    path: RelativePath
    qualname: str
    kind: Literal["function", "arrow", "function_expression", "method"]


class EcmaParameter(EcmaValue):
    pattern: str
    optional: bool
    rest: bool
    default: str | None
    annotation: str | None


class EcmaSignature(EcmaValue):
    parameters: tuple[EcmaParameter, ...]
    type_parameters: tuple[str, ...]
    return_annotation: str | None
    async_: bool = Field(alias="async")
    generator: bool


class EcmaDefinition(EcmaValue):
    id: str
    key: EcmaSymbolKey
    name: str
    language: Literal["js", "jsx", "ts", "tsx"]
    site: EvidenceSite
    signature: EcmaSignature
    syntax_hash: Digest
    ast_hash: Digest
    ambiguous: bool
    implementation: bool


class EcmaRelation(EcmaValue):
    kind: RelationKind
    source: str | None
    scope: str
    target: str
    type_only: bool
    site: EvidenceSite


class EcmaUnresolved(EcmaValue):
    kind: RelationKind
    source: str | None
    scope: str
    name: str
    reason: str
    candidates: tuple[str, ...]
    type_only: bool
    site: EvidenceSite


class EcmaExport(EcmaValue):
    path: RelativePath
    name: str
    target: str | None
    candidates: tuple[str, ...]
    reason: str | None
    type_only: bool
    site: EvidenceSite


class EcmaDiagnostic(EcmaValue):
    code: str
    message: str
    severity: Literal["error", "warning", "info"]
    site: EvidenceSite | None


class EcmaConfiguration(EcmaValue):
    root_config: RelativePath | None
    valid: bool
    module: str
    module_resolution: str
    fingerprint: Digest


class EcmaExcludedFile(EcmaValue):
    path: RelativePath
    reason: Literal["syntax_error", "case_collision", "declaration_file"]


class EcmaIdentityGap(EcmaValue):
    path: RelativePath
    qualname: str
    descendants: bool
    node_kinds: tuple[Literal["function", "arrow", "function_expression", "method"], ...]
    reason: str

    def covers(self, path: str, qualname: str, node_kind: str) -> bool:
        return path == self.path and node_kind in self.node_kinds and (
            qualname == self.qualname or self.descendants and (
                not self.qualname or qualname.startswith(self.qualname + ".")))


class EcmaAnalysis(EcmaValue):
    schema_version: Literal[1]
    analyzer_version: Literal["1.0.0"]
    compiler_version: Literal["6.0.3"]
    request_id: str
    offset_unit: Literal["utf16_code_units"]
    configuration: EcmaConfiguration
    analyzed_files: tuple[RelativePath, ...]
    excluded_files: tuple[EcmaExcludedFile, ...]
    definitions: tuple[EcmaDefinition, ...]
    identity_gaps: tuple[EcmaIdentityGap, ...]
    exports: tuple[EcmaExport, ...]
    relations: tuple[EcmaRelation, ...]
    unresolved: tuple[EcmaUnresolved, ...]
    diagnostics: tuple[EcmaDiagnostic, ...]

    @field_validator("schema_version", mode="before")
    @classmethod
    def integer_version(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("schema_version must be an integer")
        return value
