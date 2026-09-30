from dataclasses import dataclass, field


@dataclass(frozen=True)
class Evidence:
    kind: str
    source: str
    locator: str = ""
    value: object = None
    unit: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class EvidenceBundle:
    items: tuple = ()

    def add(self, evidence):
        return EvidenceBundle(self.items + (evidence,))

    def require(self, kind, source=None):
        matches = [x for x in self.items if x.kind == kind]
        if source is not None:
            matches = [x for x in matches if x.source == source]
        return tuple(matches)
