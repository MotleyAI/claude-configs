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