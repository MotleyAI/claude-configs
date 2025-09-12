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
- To get additional information on APIs and how to use them, use perplexity and context7 MCP servers
- NEVER do git add -A. ALWAYS only add specific named files