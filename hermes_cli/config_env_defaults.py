"""Factories for the optional-secret catalog, separate from configuration data."""

_OMIT = object()


def env(description, prompt, **keys):
    """One catalog entry; keyword order is preserved as dictionary key order."""
    return {'description': description, 'prompt': prompt, **keys}


def category(category, password, advanced):
    """Entry factory with usual password/advanced defaults and optional fields."""
    def make(description, prompt, url=_OMIT, *, help=_OMIT, tools=_OMIT, password=password,
             advanced=advanced):
        entry = {'description': description, 'prompt': prompt}
        entry.update((key, value) for key, value in (('help', help), ('url', url), ('tools', tools))
                     if value is not _OMIT)
        if password is not None:
            entry['password'] = password
        entry['category'] = category
        if advanced:
            entry['advanced'] = True
        return entry
    return make
