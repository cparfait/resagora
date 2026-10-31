/** Photos compressées sur l'appareil avant stockage (MOB-03) : 1600 px au plus, JPEG qualité 0,7. */
export async function compresser(fichier: Blob, cote = 1600, qualite = 0.7): Promise<Blob> {
  if (typeof createImageBitmap !== "function") return fichier;
  const image = await createImageBitmap(fichier);
  const echelle = Math.min(1, cote / Math.max(image.width, image.height));
  const toile = document.createElement("canvas");
  toile.width = Math.round(image.width * echelle);
  toile.height = Math.round(image.height * echelle);
  const contexte = toile.getContext("2d");
  if (!contexte) return fichier;
  contexte.drawImage(image, 0, 0, toile.width, toile.height);
  return new Promise((resoudre) => toile.toBlob((blob) => resoudre(blob ?? fichier), "image/jpeg", qualite));
}
