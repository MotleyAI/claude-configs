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
ONLY apply this rule for output types for LLMs, eg in motleycrew, .with_structured_output, and similar, NOT to general Pydantic classes!

- Never bulk add files to Git, always add specific named files only
- NEVER do git add -A. ALWAYS only add specific named files, make sure to add EVERY new file you create (asking me each time)
- To get additional information on APIs and how to use them, use perplexity and context7 MCP servers
- If at all possible, place all imports at the top of the file, NOT inside functions
- Whenever you do any changes to production code, ie the part that gets packaged/compiled and deployed, 
make sure you ALWAYS add solid test coverage for it, adding tests in the appropriate location.
- Whenever you do any changes to the code, afterwards run the FULL test suite for that repository, 
except integration tests, and fix any that fail.
Don't just run the tests that you think are relevant, run ALL the non-integration tests every time after changing any code in a repo.
- Do NOT pay me any compliments. If you think the instructions I give are not the best idea, and 
you have a suggestion on how to achieve the same goal better, fell free to suggest it, but only once.
If I then tell you to proceed with my original instructions, do not question me again. 
- NEVER say "You're absolutely right" or similar.
If you create any source code or test files, MAKE SURE to add any newly created files to git 
(NOT the modified ones, only add newly created ones), but don't commit them - I'll do that.
- If you can't do an operation I requested, such as read a web link, ALWAYS tell me so, and ALWAYS ask for instructions on how to proceed.
- NEVER use dataclasses! If you think you need a dataclass, inherit from Pydantic's BaseModel instead
- When I ask you a question, ANSWER THE QUESTION! Don't treat it like a rhetorical question that is really a command. 
- Put all imports at the top of the file. If that is not possible (circular imports etc.), CONFIRM WITH ME FIRST before proceeding.

NEVER ask me to find out things that you can find out yourself eg by running bash scripts - instead, run these scripts!
Except for when sudo is required - in those cases, give the commands for me to run

For Python and Javascript, ALWAYS use LSP servers to search for code, instead of grep.

- Sandbox bypass rules (when to set `dangerouslyDisableSandbox: true` and when not to): see `~/.claude/sandbox-bypass-rules.md`.
