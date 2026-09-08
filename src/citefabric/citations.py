"""Bibliographic export. Claim assessments live in the parallel manifest."""

from .models import Edition, MetadataSnapshot


def csl(edition: Edition, metadata: MetadataSnapshot) -> dict:
    item: dict = dict(
        id=edition.edition_id,
        type="article-journal"
        if edition.kind == "journal_article"
        else "paper-conference"
        if edition.kind == "conference_paper"
        else "article",
        title=metadata.title,
    )
    authors = []
    for author in metadata.authors:
        if author.organization or not author.family:
            authors.append({"literal": author.organization or author.display_name})
        else:
            name = {"family": author.family}
            if author.given:
                name["given"] = author.given
            authors.append(name)
    if authors:
        item["author"] = authors
    date = [metadata.issued.year, metadata.issued.month, metadata.issued.day]
    if date[0]:
        item["issued"] = {"date-parts": [[part for part in date if part is not None]]}
    if metadata.venue:
        item["container-title"] = metadata.venue
    for external in edition.external_ids:
        if external.namespace == "doi":
            item["DOI"] = external.value
        elif external.namespace == "arxiv":
            item["URL"] = "https://arxiv.org/abs/" + external.value + (external.version or "")
    return item


def escape(value: str) -> str:
    substitutions = {
        "\\": r"\textbackslash{}",
        "{": r"\{",
        "}": r"\}",
        "%": r"\%",
        "&": r"\&",
        "_": r"\_",
        "#": r"\#",
        "$": r"\$",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(
        substitutions.get(char, char) for char in value.replace("\r", " ").replace("\n", " ")
    )


def bibtex(edition: Edition, metadata: MetadataSnapshot) -> str:
    fields = {"title": escape(metadata.title)}
    if metadata.authors:
        names = []
        for author in metadata.authors:
            if author.organization or not author.family:
                names.append("{" + escape(author.organization or author.display_name) + "}")
            else:
                names.append(
                    escape(author.family) + (", " + escape(author.given) if author.given else "")
                )
        fields["author"] = " and ".join(names)
    if metadata.issued.year:
        fields["year"] = str(metadata.issued.year)
    if metadata.venue:
        fields["journal" if edition.kind == "journal_article" else "booktitle"] = escape(
            metadata.venue
        )
    for external in edition.external_ids:
        if external.namespace == "doi":
            fields["doi"] = escape(external.value)
        elif external.namespace == "arxiv":
            fields.update(
                archivePrefix="arXiv", eprint=escape(external.value + (external.version or ""))
            )
    kind = (
        "article"
        if edition.kind == "journal_article"
        else "inproceedings"
        if edition.kind == "conference_paper"
        else "misc"
    )
    key = "cf" + edition.edition_id.replace("-", "")
    return (
        "@"
        + kind
        + "{"
        + key
        + ",\n"
        + ",\n".join("  " + k + " = {" + v + "}" for k, v in fields.items())
        + "\n}"
    )
