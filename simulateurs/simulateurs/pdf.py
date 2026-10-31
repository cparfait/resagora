"""Génération de PDF minimaux valides (une page de texte), sans dépendance."""

from __future__ import annotations


def _echapper(texte: str) -> str:
    return texte.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def pdf_texte(lignes: list[str]) -> bytes:
    """PDF 1.7 d'une page A4 avec des lignes de texte en Helvetica (encodage WinAnsi)."""
    flux = ["BT", "/F1 11 Tf", "50 790 Td", "14 TL"]
    for ligne in lignes:
        flux.append(f"({_echapper(ligne)}) Tj T*")
    flux.append("ET")
    contenu = "\n".join(flux).encode("cp1252", errors="replace")
    objets = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(contenu)).encode() + b" >>\nstream\n" + contenu + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    sortie = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    positions = []
    for numero, objet in enumerate(objets, start=1):
        positions.append(len(sortie))
        sortie += f"{numero} 0 obj\n".encode() + objet + b"\nendobj\n"
    debut_table = len(sortie)
    sortie += f"xref\n0 {len(objets) + 1}\n0000000000 65535 f \n".encode()
    for position in positions:
        sortie += f"{position:010d} 00000 n \n".encode()
    sortie += f"trailer\n<< /Size {len(objets) + 1} /Root 1 0 R >>\nstartxref\n{debut_table}\n%%EOF\n".encode()
    return bytes(sortie)
