"""Module-level SDK tasks used by fresh-process reload tests."""

from typing import Annotated

from pydantic import BaseModel

from constructicon.sdk import port_type, task


class EchoInput(BaseModel):
    text: str


class EchoOutput(BaseModel):
    text: str


@task("sdk-fixture/echo", output="echo")
async def echo(
    value: Annotated[EchoInput, port_type("sdk-fixture/EchoInput")],
) -> Annotated[EchoOutput, port_type("sdk-fixture/EchoOutput")]:
    return EchoOutput(text=value.text)
