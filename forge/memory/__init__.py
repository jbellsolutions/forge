"""L1 memory — ReasoningBank + git journal + Obsidian vault + .claude/ contract + cross-project genome."""
from .claude_dir import ClaudeDir
from .genome import genome, genome_path
from .git_journal import GitJournal
from .obsidian import Note, ObsidianVault, index_into_reasoning_bank
from .promotion import PromotionResult, promote
from .reasoning_bank import Memory, ReasoningBank

__all__ = [
    "ClaudeDir", "GitJournal", "Memory", "Note",
    "ObsidianVault", "PromotionResult", "ReasoningBank",
    "genome", "genome_path",
    "index_into_reasoning_bank", "promote",
]
