import json
from pathlib import Path

from enums.bot_entity import BotEntity
from enums.language import Language


class Localizator:
    _i18n_dir = Path("./i18n")
    _cache: dict[Language, dict] = {}
    # Texts edited by admins in the bot: (language value, entity name, key) -> text. Loaded from the DB.
    _overrides: dict[tuple[str, str, str], str] = {}

    @classmethod
    def set_overrides(cls, overrides: dict[tuple[str, str, str], str]) -> None:
        cls._overrides = dict(overrides)

    @classmethod
    def set_override(cls, language: Language, entity: BotEntity, key: str, value: str | None) -> None:
        if value is None:
            cls._overrides.pop((language.value, entity.name, key), None)
        else:
            cls._overrides[(language.value, entity.name, key)] = value

    @classmethod
    def get_override(cls, language: Language, entity: BotEntity, key: str) -> str | None:
        return cls._overrides.get((language.value, entity.name, key))

    @classmethod
    def get_default_text(cls, language: Language, entity: BotEntity, key: str) -> str:
        try:
            return cls._load_language(language)[entity.name.lower()][key]
        except KeyError:
            if language == Language.EN:
                raise
            return cls.get_default_text(Language.EN, entity, key)

    @classmethod
    def _load_language(cls, language: Language) -> dict:
        cached = cls._cache.get(language)
        if cached is not None:
            return cached
        path = cls._i18n_dir / f"{language.value}.json"
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
        cls._cache[language] = data
        return data

    @classmethod
    def get_text(cls, language: Language, entity: BotEntity, key: str) -> str:
        override = cls._overrides.get((language.value, entity.name, key))
        if override is not None:
            return override
        try:
            language_payload = cls._load_language(language)
            return language_payload[entity.name.lower()][key]
        except KeyError:
            if language == Language.EN:
                raise
            return cls.get_text(Language.EN, entity, key)

    @classmethod
    def get_all_texts(cls, entity: BotEntity, key: str) -> set[str]:
        localized_texts = set()
        for locale_file in cls._i18n_dir.glob("*.json"):
            try:
                language = Language(locale_file.stem)
            except ValueError:
                continue
            localized_texts.add(cls.get_text(language, entity, key))
            # Old keyboards keep the previous button name, so the default text keeps working too.
            localized_texts.add(cls.get_default_text(language, entity, key))
        return localized_texts

    @classmethod
    def clear_cache(cls) -> None:
        cls._cache.clear()
