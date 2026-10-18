import pytest

from supps.model import Variant, group_variants
from supps.normalize import classify, is_sample, net_weight, parse_grams, protein_per_100g, whey_type


@pytest.mark.parametrize(
    "title, kind",
    [
        ("Créatine (Creapure®) en poudre", "creatine"),
        ("Créatine Monohydrate Creapure® en Poudre 500 g", "creatine"),
        ("Creatina y electrolitos", None),
        ("Café con proteína de suero", None),
        ("Creatina monohidrato en polvo (200 mesh)", "creatine"),
        ("Créatine (Creapure®) en gélules", None),
        ("WEIDER Gummies creatina micronizada cereza x60", None),
        ("Activ'énergie Complexe Créatine", None),
        ("Evowhey protein", "whey"),
        ("Whey Native Isolate (Low lactose)", "whey"),
        ("Lean Gainer Whey Avoine", None),
        ("Isolat de Caséine Micellaire Native", None),
        ("Recuperador muscular (3:1 Recovery+ con aislado de Whey)", None),
        ("Proteína de guisante aislada 2.0", None),
        ("Nutrimuscle Recovery Duo - Whey Protimuscle + Creatine Creapure", None),
    ],
)
def test_classify(title, kind):
    assert classify(title) == kind


@pytest.mark.parametrize(
    "text, grams",
    [
        ("Bote de 300 g / 60 tomas / Neutro", 300),
        ("2Kg", 2000),
        ("1,5 kg", 1500),
        ("5 lbs", 2268.0),
        ("Pot de 433g / Myrtille", 433),
        ("Sobre de 5 g / Neutro", None),
        ("22 g de protéines par portion", None),
        ("2 x 1 kg", 2000),
        ("Whey 30 g/serving 900 g", 900),
    ],
)
def test_parse_grams(text, grams):
    assert parse_grams(text) == grams


def test_net_weight():
    assert net_weight("le sachet de 180 g équivaut à 60 portions") == 180
    assert net_weight("Poids net : 1 kg") == 1000


@pytest.mark.parametrize(
    "text, protein",
    [
        # per-serving column only (Nutrimuscle)
        ("Par portion (30g) Pour 100g Apports de référence | Énergie | 471 kJ | Protéines | 24,4 g | Sel", 81.3),
        # dry matter must be skipped in favour of "as sold" (Novoma)
        ("Proteínas (materia seca) | Natural: 90,7 g / 100 g | Proteínas (materia húmeda) (producto terminado) | "
         "Natural: 85,45 g / 100 g", 85.45),
        ("Valeurs nutritionnelles pour 100 g par dose de 30 g Energie 1600 kJ Protéines 80 g 24 g Glucides", 80),
        ("Información nutricional Por 100 g Por dosis (30 g) Proteínas 78,5 g 23,6 g", 78.5),
        # HSN: serving first, then 100 g
        ("Tamaño de la dosis: 1 dosificador de 70ml (30g) Por servicio Por 100g Valor Energético 496kJ "
         "Proteínas 24 g 78g Sal 0,30 g 1g", 78),
        ("con un 75% de proteínas de suero", 75),
        ("Protein 22 g per 30 g serving", 73.3),
        ("Ideal para ganar masa muscular", None),
    ],
)
def test_protein(text, protein):
    assert protein_per_100g(text) == protein


def test_whey_type():
    assert whey_type("Evolate 2.0 (whey isolate CFM)") == "isolate"
    assert whey_type("Evoexcel (whey protein isolate + concentrate)") == "blend"
    assert whey_type("Evohydro 2.0 (hydro whey)") == "hydrolysed"
    assert whey_type("Evowhey protein") == "concentrate"


def test_group_variants_prefers_in_stock_and_counts_flavours():
    sizes = group_variants(
        [
            Variant("Chocolate", 1000, 30.0, 40.0, True),
            Variant("Vanilla", 1000, 28.0, None, False),
            Variant("Neutral", 1000, 31.0, None, True),
            Variant("Neutral", 2000, 55.0, None, False),
        ]
    )
    assert sizes[1000]["price"] == 30.0 and sizes[1000]["available"] is True and sizes[1000]["flavours"] == 3
    assert sizes[1000]["list_price"] == 40.0
    assert sizes[2000]["available"] is False


@pytest.mark.parametrize(
    "label, sample",
    [("Sachet de 1 kg", False), ("Sobre de 5 g / Neutro", True), ("Caja (24 monodosis) / Neutro", True),
     ("Bote de 300 g / 60 tomas", False), ("Monodosis (30g)", True), ("2Kg", False)],
)
def test_is_sample(label, sample):
    assert is_sample(label) is sample
