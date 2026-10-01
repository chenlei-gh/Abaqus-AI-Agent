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
    """Immutable ordered collection of typed evidence items."""
    items: tuple = ()

    def add(self, evidence):
        if not isinstance(evidence, Evidence):
            raise TypeError("EvidenceBundle accepts Evidence instances")
        return EvidenceBundle(self.items + (evidence,))

    def extend(self, evidence_items):
        bundle = self
        for evidence in evidence_items:
            bundle = bundle.add(evidence)
        return bundle

    def require(self, kind, source=None):
        matches = [x for x in self.items if x.kind == kind]
        if source is not None:
            matches = [x for x in matches if x.source == source]
        return tuple(matches)

    def __iter__(self):
        return iter(self.items)

    def __len__(self):
        return len(self.items)

    def __bool__(self):
        return bool(self.items)
