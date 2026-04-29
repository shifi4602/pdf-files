from __future__ import annotations
from dependency_injector import containers, providers

from infrastructure.pdf_reader   import PdfReader
from infrastructure.detector     import KeywordDetector
from parsers.parser_type_a       import TypeAParser
from parsers.parser_type_b       import TypeBParser
from generators.generator_type_a import TypeAGenerator
from generators.generator_type_b import TypeBGenerator
from transformation.strategies   import (
    TypeATransformationStrategy,
    TypeBTransformationStrategy,
    ValidatingStrategyDecorator,
)
from transformation.service      import TransformationService


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

    # Transformation service — strategy registry wired here (Registry pattern).
    # Each strategy is wrapped in ValidatingStrategyDecorator (Decorator pattern).
    # Adding a new report type = one new strategy class + one registry entry.
    transformation_service = providers.Singleton(
        TransformationService,
        strategy_registry={
            "TYPE_A": ValidatingStrategyDecorator(TypeATransformationStrategy()),
            "TYPE_B": ValidatingStrategyDecorator(TypeBTransformationStrategy()),
        },
    )

    # PDF generators — one per report type
    generator_a = providers.Singleton(TypeAGenerator)
    generator_b = providers.Singleton(TypeBGenerator)

    # ── Collections (resolved at call time) ───────────────────────────────────
    parsers    = providers.List(parser_a,    parser_b)
    generators = providers.List(generator_a, generator_b)
