def test_only_dice_touches_random():
    """CLAUDE.md §7: `dice.py` is the only module that touches `random`.

    Ledger A12 found two modules importing it directly. Both were seeded, so
    determinism held, but a stated invariant nobody checks is a comment.
    """
    import ast
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "src"
    offenders = []
    for path in src.rglob("*.py"):
        if path.relative_to(src).as_posix() == "utils/dice.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            if any(n == "random" or n.startswith("random.") for n in names):
                offenders.append(path.relative_to(src).as_posix())
    assert offenders == [], f"import randomness through src.utils.dice: {offenders}"
