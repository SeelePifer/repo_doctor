def normalize_ws(text: str) -> str:
    return " ".join(text.split())


def snippet_matches(snippet: str, actual: str) -> bool:
    left = normalize_ws(snippet)
    right = normalize_ws(actual)
    if not left or not right:
        return False
    return left in right


def chunk_ranges(line_count: int, size: int = 80, overlap: int = 15) -> list[tuple[int, int]]:
    if line_count <= 0:
        return []
    step = max(size - overlap, 1)
    ranges: list[tuple[int, int]] = []
    start = 1
    while start <= line_count:
        end = min(start + size - 1, line_count)
        ranges.append((start, end))
        if end == line_count:
            break
        start += step
    return ranges


def clamp_text(text: str, max_chars: int = 4000) -> str:
    if len(text) <= max_chars:
        return text
    clipped = text[:max_chars]
    if "\n" in clipped:
        clipped = clipped.rsplit("\n", 1)[0]
    return clipped


def line_window(text: str, start_line: int, end_line: int) -> str:
    lines = text.splitlines()
    selected = lines[start_line - 1 : end_line]
    return "\n".join(selected)


def normalize_repo_path(path: str) -> str:
    cleaned = path.replace("\\", "/").strip()
    if cleaned.startswith("./"):
        cleaned = cleaned[2:]
    if cleaned.startswith("a/") or cleaned.startswith("b/"):
        cleaned = cleaned[2:]
    return cleaned


def files_in_diff(diff: str) -> list[str]:
    found: list[str] = []
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            parts = line.split()
            if len(parts) >= 4:
                found.append(normalize_repo_path(parts[3]))
            continue
        if line.startswith("+++ "):
            name = line[4:].split("\t", 1)[0].strip()
            if name != "/dev/null":
                found.append(normalize_repo_path(name))
    unique: list[str] = []
    for path in found:
        if path and path not in unique:
            unique.append(path)
    return unique
