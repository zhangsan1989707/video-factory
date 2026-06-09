"""Command entry for the local console."""

import typer

from src.console.server import run_server


app = typer.Typer(
    name="github-video-console",
    help="本机视频工厂控制台",
    add_completion=False,
)


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="控制台监听地址"),
    port: int = typer.Option(8765, "--port", help="控制台端口"),
    open_browser: bool = typer.Option(False, "--open", help="启动后自动打开浏览器"),
):
    """启动本机视频工厂控制台"""
    run_server(host=host, port=port, open_browser=open_browser)


if __name__ == "__main__":
    app()
