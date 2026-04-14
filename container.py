from __future__ import annotations
from dependency_injector import containers, providers

from pdf_reader       import PdfReader
from detector         import KeywordDetector
from parser_type_a    import TypeAParser
from parser_type_b    import TypeBParser
from variation_type_a import TypeAVariationEngine
from variation_type_b import TypeBVariationEngine
from generator_type_a import TypeAGenerator
from generator_type_b import TypeBGenerator


class Container(containers.DeclarativeContainer):
    """
    Dependency-injection container.

    Design (interview note):
    ─────────────────────────────────────────────────────────────────────
    Nothing outside this file calls a constructor directly.
    main.py asks the container for ready-made objects.
    This means every component is swappable for a fake in tests by simply
    overriding the provider:

        container.pdf_reader.override(FakePdfReader())
    ─────────────────────────────────────────────────────────────────────

    All concrete classes are registered as Singletons — they are stateless
    so one instance per process is sufficient and efficient.
    """

    config = providers.Configuration()

    # ── Infrastructure ─────────────────────────────────────────────────────────
    pdf_reader = providers.Singleton(PdfReader, dpi=300)
    detector   = providers.Singleton(KeywordDetector)

    # Parsers — one per report type (Strategy pattern)
    parser_a = providers.Singleton(TypeAParser)
    parser_b = providers.Singleton(TypeBParser)

    # Variation engines — one per report type
    variation_a = providers.Singleton(TypeAVariationEngine)
    variation_b = providers.Singleton(TypeBVariationEngine)

    # PDF generators — one per report type
    generator_a = providers.Singleton(TypeAGenerator)
    generator_b = providers.Singleton(TypeBGenerator)

    # ── Collections (resolved at call time) ───────────────────────────────────
    parsers    = providers.List(parser_a,    parser_b)
    variations = providers.List(variation_a, variation_b)
    generators = providers.List(generator_a, generator_b)
