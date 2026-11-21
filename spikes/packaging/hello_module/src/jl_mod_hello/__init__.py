import humanize


class Module:
    def register(self, ctx) -> None:
        ctx.add_popup_action("Hello", self.hello)

    def hello(self, word: str) -> str:
        return f"hello from a module, word={word}, {humanize.naturalsize(1_500_000)}"
