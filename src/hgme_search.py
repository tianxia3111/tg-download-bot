from dataclasses import dataclass, field


@dataclass
class Candidate:
    kind: str
    id: str
    title: str
    year: int = 0
    score: str = ""
    tags: list[str] = field(default_factory=list)
    url: str = ""


@dataclass
class MagnetItem:
    title: str
    size: str
    tag: str
    magnet: str


def search(keyword: str) -> list[Candidate]:
    from hgme_proxy import get_session
    session = get_session()
    return session.search(keyword)


def get_torrents(kind: str, id_: str) -> list[MagnetItem]:
    from hgme_proxy import get_session
    session = get_session()
    return session.get_torrents(kind, id_)
