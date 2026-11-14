
import flet as ft


def main(page: ft.Page):
    page.title = "TerraCode | Plataforma Agrointeligente"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.bgcolor = "#F3F7F2"
    page.padding = 0
    page.scroll = ft.ScrollMode.AUTO

    VERDE = "#237A31"
    VERDE_OSCURO = "#14532D"
    VERDE_CLARO = "#E8F5E9"
    GRIS = "#64748B"

    # MENSAJES
    mensaje = ft.Text("", size=13, color="#D32F2F")

    # CAMPOS DEL LOGIN
    correo = ft.TextField(
        label="Correo electrónico",
        hint_text="ejemplo@correo.com",
        prefix_icon=ft.Icons.EMAIL_OUTLINED,
        border_radius=12,
        border_color="#D5E3D5",
        focused_border_color=VERDE,
        keyboard_type=ft.KeyboardType.EMAIL,
        width=360,
    )

    contrasena = ft.TextField(
        label="Contraseña",
        password=True,
        can_reveal_password=True,
        prefix_icon=ft.Icons.LOCK_OUTLINE,
        border_radius=12,
        border_color="#D5E3D5",
        focused_border_color=VERDE,
        width=360,
    )

    # PANTALLA DE INVITADO
    def entrar_invitado(e):
        page.controls.clear()
        page.bgcolor = "#F3F7F2"

        page.add(
            ft.Container(
                expand=True,
                alignment=ft.Alignment.CENTER,
                padding=30,
                content=ft.Column(
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    alignment=ft.MainAxisAlignment.CENTER,
                    controls=[
                        ft.Icon(
                            ft.Icons.ECO,
                            size=75,
                            color=VERDE,
                        ),
                        ft.Text(
                            "Bienvenido a TerraCode",
                            size=30,
                            weight=ft.FontWeight.BOLD,
                            color=VERDE_OSCURO,
                            text_align=ft.TextAlign.CENTER,
                        ),
                        ft.Text(
                            "Explora y analiza cualquier región del planeta.",
                            size=16,
                            color=GRIS,
                            text_align=ft.TextAlign.CENTER,
                        ),
                        ft.Container(height=20),
                        ft.Button(
                            content="Iniciar análisis agrícola",
                            icon=ft.Icons.TRAVEL_EXPLORE,
                            bgcolor=VERDE,
                            color="white",
                            height=50,
                            on_click=lambda e: mostrar_mensaje(
                                "Próximamente: análisis satelital"
                            ),
                        ),
                        ft.TextButton(
                            content="Volver al inicio",
                            on_click=lambda e: mostrar_login(),
                        ),
                    ],
                ),
            )
        )
        page.update()

    def mostrar_mensaje(texto):
        page.show_dialog(
            ft.SnackBar(
                content=ft.Text(texto),
                bgcolor=VERDE_OSCURO,
            )
        )

    # VALIDACIÓN DEL FORMULARIO
    def iniciar_sesion(e):
        if not correo.value or not contrasena.value:
            mensaje.value = "Completa todos los campos."
        else:
            mensaje.value = (
                "El inicio de sesión estará disponible "
                "cuando conectemos la autenticación."
            )
        page.update()

    def iniciar_google(e):
        mensaje.value = (
            "La autenticación con Google aún no está configurada."
        )
        page.update()

    # PANEL INFORMATIVO
    panel_izquierdo = ft.Container(
        expand=1,
        bgcolor=VERDE_OSCURO,
        padding=45,
        border_radius=ft.BorderRadius.only(
            top_right=35,
            bottom_right=35,
        ),
        content=ft.Column(
            alignment=ft.MainAxisAlignment.CENTER,
            horizontal_alignment=ft.CrossAxisAlignment.START,
            spacing=24,
            controls=[
                ft.Container(
                    bgcolor="#FFFFFF20",
                    padding=15,
                    border_radius=18,
                    content=ft.Icon(
                        ft.Icons.ECO,
                        size=55,
                        color="#A5D6A7",
                    ),
                ),
                ft.Text(
                    "TerraCodex",
                    size=44,
                    weight=ft.FontWeight.BOLD,
                    color="white",
                ),
                ft.Text(
                    "Inteligencia para cultivar el futuro.",
                    size=23,
                    weight=ft.FontWeight.W_500,
                    color="#D1FAE5",
                ),
                ft.Text(
                    "Analiza el suelo, clima y vegetación "
                    "de cualquier lugar del planeta mediante "
                    "datos geoespaciales e inteligencia artificial.",
                    size=16,
                    color="#D5E8D8",
                ),
                ft.Divider(color="#FFFFFF40"),
                ft.Row(
                    controls=[
                        ft.Icon(
                            ft.Icons.PUBLIC,
                            color="#A5D6A7",
                        ),
                        ft.Text(
                            "Exploración geográfica global",
                            color="white",
                        ),
                    ]
                ),
                ft.Row(
                    controls=[
                        ft.Icon(
                            ft.Icons.CLOUD_OUTLINED,
                            color="#A5D6A7",
                        ),
                        ft.Text(
                            "Información climática y satelital",
                            color="white",
                        ),
                    ]
                ),
                ft.Row(
                    controls=[
                        ft.Icon(
                            ft.Icons.SPA_OUTLINED,
                            color="#A5D6A7",
                        ),
                        ft.Text(
                            "Recomendaciones inteligentes",
                            color="white",
                        ),
                    ]
                ),
            ],
        ),
    )

    # FORMULARIO DE ACCESO
    formulario = ft.Container(
        expand=1,
        padding=35,
        alignment=ft.Alignment.CENTER,
        content=ft.Column(
            alignment=ft.MainAxisAlignment.CENTER,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=18,
            controls=[
                ft.Icon(
                    ft.Icons.ECO,
                    size=55,
                    color=VERDE,
                ),
                ft.Text(
                    "Bienvenido a TerraCodex",
                    size=27,
                    weight=ft.FontWeight.BOLD,
                    color=VERDE_OSCURO,
                    text_align=ft.TextAlign.CENTER,
                ),
                ft.Text(
                    "Accede a tu plataforma de análisis agrícola",
                    size=14,
                    color=GRIS,
                    text_align=ft.TextAlign.CENTER,
                ),
                ft.Container(height=10),
                correo,
                contrasena,
                mensaje,
                ft.Button(
                    content="Iniciar sesión",
                    icon=ft.Icons.LOGIN,
                    width=360,
                    height=52,
                    bgcolor=VERDE,
                    color="white",
                    on_click=iniciar_sesion,
                ),
                ft.Row(
                    width=360,
                    alignment=ft.MainAxisAlignment.CENTER,
                    controls=[
                        ft.Text(
                            "O continúa con",
                            color=GRIS,
                            size=13,
                        )
                    ],
                ),
                ft.OutlinedButton(
                    content="Continuar con Google",
                    icon=ft.Icons.ACCOUNT_CIRCLE_OUTLINED,
                    width=360,
                    height=50,
                    on_click=iniciar_google,
                ),
                ft.Container(
                    width=360,
                    bgcolor=VERDE_CLARO,
                    border_radius=12,
                    padding=12,
                    content=ft.Column(
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            ft.Text(
                                "¿Solo deseas explorar?",
                                weight=ft.FontWeight.BOLD,
                                color=VERDE_OSCURO,
                            ),
                            ft.Text(
                                "No necesitas registrarte para "
                                "consultar información.",
                                size=12,
                                color=GRIS,
                                text_align=ft.TextAlign.CENTER,
                            ),
                            ft.TextButton(
                                content="Explorar sin cuenta →",
                                on_click=entrar_invitado,
                            ),
                        ],
                    ),
                ),
                ft.Text(
                    "© 2026 TerraCodex | Agrointeligencia",
                    size=11,
                    color=GRIS,
                ),
            ],
        ),
    )

    # INTERFAZ PRINCIPAL
    def mostrar_login():
        page.controls.clear()
        page.bgcolor = "#F3F7F2"

        # Diseño adaptable a escritorio y móvil
        if page.width and page.width < 800:
            contenido = ft.Column(
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    formulario,
                ],
            )
        else:
            contenido = ft.Row(
                expand=True,
                spacing=0,
                controls=[
                    panel_izquierdo,
                    formulario,
                ],
            )

        page.add(
            ft.Container(
                expand=True,
                content=contenido,
            )
        )
        page.update()

    def redimensionar(e):
        mostrar_login()

    page.on_resize = redimensionar
    mostrar_login()


ft.run(main)
