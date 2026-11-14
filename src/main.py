
import flet as ft


def main(page: ft.Page):
    page.title = "TerraCode"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.padding = 30

    titulo = ft.Text(
        "TerraCode",
        size=32,
        weight=ft.FontWeight.BOLD,
        color=ft.Colors.GREEN_800,
    )

    descripcion = ft.Text(
        "Plataforma inteligente de análisis agrícola",
        size=16,
    )

    resultado = ft.Text("")

    def analizar(e):
        resultado.value = "Análisis iniciado correctamente"
        page.update()

    page.add(
        titulo,
        descripcion,
        ft.Button(
            content="Iniciar análisis",
            on_click=analizar,
        ),
        resultado,
    )


ft.run(main)
