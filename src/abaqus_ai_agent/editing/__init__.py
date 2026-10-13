"""Controlled Model Editing and In-Place Mutation Prevention Module (Phase P1.4 / P1.5)."""

from .inp_editor import (
    InpEditOperation,
    InpEditAuditRecord,
    ControlledInpEditor,
    edit_inp_file,
)

__all__ = [
    "InpEditOperation",
    "InpEditAuditRecord",
    "ControlledInpEditor",
    "edit_inp_file",
]
