When using LLMs to output Pydantic classes, ALWAYS make sure these classes don't contain 
any Dict-typed fields, instead use lists of helper classes with a name field. So for example instead of 
```python
class Foo(BaseModel):
    bars: Dict[str, Bar]
```
you should write
```python
class Baz(BaseModel):
    name: str
    value: Bar
    
class Foo(BaseModel):
    bars: List[Baz]
```

```
- Never bulk add files to Git, always add specific named files only
- NEVER do git add -A. ALWAYS only add specific named files
- To get additional information on APIs and how to use them, use perplexity and context7 MCP servers
- If at all possible, place all imports at the top of the file, NOT inside functions
- Whenever you do any changes to the code, afterwards run the FULL test suite for that repository, and fix any that fail.
Don't just run the tests that you think are relevant, run ALL the tests every time after changing any code in a repo.
