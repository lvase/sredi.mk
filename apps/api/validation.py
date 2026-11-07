from rest_framework.exceptions import ValidationError


def identifier(value, name):
    if value in (None, ""):
        return None
    text = str(value)
    if not text.isascii() or not text.isdigit() or len(text) > 19 or not 0 < int(text) <= 9223372036854775807:
        raise ValidationError({name: ["Изберете валиден идентификатор."]})
    return int(text)


def flag(value, name):
    if value in (None, "", "0", "false"):
        return False
    if value in ("1", "true"):
        return True
    raise ValidationError({name: ["Користете 0 или 1."]})
