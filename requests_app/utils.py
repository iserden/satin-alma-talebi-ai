import re
import unicodedata


def normalize_product_text(value: str | None) -> str:
    """
    Ürün isimlerini karşılaştırmaya uygun standart metne dönüştürür.

    Örnek:
    "Coca-Cola 1 LT" → "coca cola 1 lt"
    "PATATEŞ"        → "patates"
    """

    if not value:
        return ""

    text = str(value).strip().casefold()

    # Türkçedeki noktasız ı karakterini standart i hâline getirir.
    text = text.replace("ı", "i")

    # Ş, Ğ, Ü, Ö, Ç gibi karakterleri sade biçime dönüştürür.
    text = unicodedata.normalize("NFKD", text)

    text = "".join(
        character
        for character in text
        if not unicodedata.combining(character)
    )

    # Harf, rakam ve boşluk dışındaki karakterleri boşluk yapar.
    text = re.sub(
        pattern=r"[^a-z0-9]+",
        repl=" ",
        string=text,
    )

    # Fazla boşlukları temizler.
    return " ".join(text.split())