'''Prompt template engine.'''
def format_prompt(template: str, variables: dict[str, str]) -> str:
    if not template:
        return ""
    result = template
    for key, val in variables.items():
        result = result.replace(f"{{{key}}}", str(val))
    return result
