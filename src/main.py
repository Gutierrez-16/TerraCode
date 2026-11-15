import asyncio
import logging
from os import getenv
from datetime import date, timedelta
from ipaddress import ip_address
from math import atan, ceil, degrees, isfinite, log, pi, radians, sin, sinh, tan
from statistics import mean
from urllib.parse import urlsplit

import flet as ft
import flet.canvas as cv
import flet_geolocator as gps
import flet_map as fm
import flet_webview as fwv

import nasa
import map_provider
from globe_view import GlobeView
from place_search import find_places, google_location, google_places, google_search_enabled
from uuid import uuid4

MAP_START = (15, 0)
MAP_START_ZOOM = 2
PARCEL_ZOOM = 15
LOCATION_TIMEOUT = 10
PARCEL_LOCATION_ACCURACY = 100


def location_zoom(accuracy):
    """Keep the device's uncertainty visible at the starting zoom."""
    return max(2, min(16, int(log(10_000_000 / max(1, accuracy), 2))))


def valid_position(position):
    return (position is not None
            and position.latitude is not None and -85 <= position.latitude <= 85
            and position.longitude is not None and -180 <= position.longitude <= 180
            and position.accuracy is not None and isfinite(position.accuracy)
            and position.accuracy >= 0 and not position.mocked)


def browser_url(url):
    parts = urlsplit(url or "")
    scheme = {"ws": "http", "wss": "https"}.get(parts.scheme, parts.scheme)
    return parts._replace(scheme=scheme)


def globe_document_url(url):
    parts = browser_url(url)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return None
    return parts._replace(path="/earth3d.html",
                          query="", fragment="").geturl()


def web_location_allowed(url):
    origin = browser_url(url)
    if origin.scheme != "http":
        return True
    host = origin.hostname or ""
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


async def main(page: ft.Page):
    page.title = "TerraSprout · Explorador agrícola"
    page.theme = ft.Theme(color_scheme_seed="#21694E")
    page.theme_mode = ft.ThemeMode.LIGHT
    page.bgcolor = "#EFF4EF"
    page.padding = 0
    page.spacing = 0
    origin = browser_url(page.url)
    project_url = origin._replace(path="/landing/inicio.html",
                                  query="", fragment="").geturl()
    home_url = origin._replace(path="/", query="", fragment="").geturl()
    map_url = origin._replace(path="/mapa", query="", fragment="").geturl()
    chrome_url = origin._replace(path="/landing/chrome.html", query="", fragment="").geturl()
    globe_url = globe_document_url(page.url) if page.web and getenv("GLOBE_MODE", "3d") == "3d" else None
    use_3d = globe_url is not None

    geo = gps.Geolocator()
    page.services.append(geo)
    coords = ft.Text("Toca el mapa para seleccionar la parcela.", selectable=True)
    status = ft.Text()
    location_status = ft.Text(color="#FFFFFF", size=13)
    toast_job = None

    def notify(message, color="#173455", dismiss=True):
        nonlocal toast_job
        if toast_job:
            toast_job.cancel()
        location_status.value = message
        toast.bgcolor = color
        toast.visible = True
        page.update()

        async def hide():
            await asyncio.sleep(4)
            toast.visible = False
            page.update()

        toast_job = asyncio.create_task(hide()) if dismiss else None
    climate = ft.Column([ft.Text("Selecciona una parcela para consultar NASA POWER.")])
    satellite = ft.Column([ft.Text("Selecciona una parcela para buscar escenas ECOSTRESS.")])
    lat = ft.TextField(label="Latitud", width=155)
    lon = ft.TextField(label="Longitud", width=155)
    end = ft.TextField(label="Hasta (AAAA-MM-DD)", value=str(date.today()), width=180)
    start = ft.TextField(label="Desde (AAAA-MM-DD)", value=str(date.today() - timedelta(days=89)), width=180)
    version = 0
    position_revision = 0
    locating = False
    gps_position = None
    drawing = False
    vertices = []
    saved_vertices = []
    selected_vertex = None
    scene_request = None
    climate_job = None
    scene_job = None
    selection_key = None

    async def choose(event):
        nonlocal selected_vertex
        if locating:
            return
        point = fm.MapLatitudeLongitude(event.coordinates.latitude,
                                        (event.coordinates.longitude + 180) % 360 - 180)
        if drawing:
            if (last_camera.zoom if last_camera else globe.initial_zoom) < PARCEL_ZOOM:
                draw_hint.value = "Acercando la zona. Marca el primer vértice cuando veas los límites."
                page.update()
                await focus_map(point, 16)
                return
            if selected_vertex is None:
                if vertices and point == vertices[-1]:
                    return
                vertices.append(point)
            else:
                vertices[selected_vertex] = point
                selected_vertex = None
            update_boundary()
            return
        await select(point.latitude, point.longitude)

    marker = fm.MarkerLayer(markers=[])
    handles = fm.MarkerLayer(markers=[])
    outline = fm.PolylineLayer(polylines=[])
    boundary = fm.PolygonLayer(polygons=[])
    gps_accuracy = fm.CircleLayer(circles=[])
    last_camera = None

    def remember_camera(event):
        nonlocal last_camera
        last_camera = event.camera

    globe = fm.Map(
        expand=True, initial_center=fm.MapLatitudeLongitude(*MAP_START), initial_zoom=MAP_START_ZOOM,
        on_tap=choose, on_position_change=remember_camera, layers=[boundary, outline, marker, handles],
    )
    attribution = ft.Text(map_provider.OSM_CREDIT, color="#FFFFFF", size=12)
    credit_job = None
    google_credentials = None
    google_url = None
    active_provider = None
    provider_started = False
    provider_focus = None
    tiles = fm.TileLayer(url_template=map_provider.OSM_URL, keep_buffer=1, pan_buffer=0,
                         user_agent_package_name="TerraSprout/1.0")

    def set_basemap(provider, url, credit, zoom=19):
        nonlocal active_provider
        if provider != active_provider:
            tiles.url_template = url
            tiles.max_native_zoom = zoom
            if active_provider is None:
                globe.layers = [tiles, gps_accuracy, boundary, outline, marker, handles]
            active_provider = provider
        attribution.value = credit

    def osm_basemap():
        set_basemap("osm", map_provider.OSM_URL, map_provider.OSM_CREDIT)

    async def update_google_credit(camera, initial=False):
        if not initial:
            await asyncio.sleep(.5)
        point = camera.center if camera else provider_focus
        zoom = camera.zoom if camera else 13 if point else MAP_START_ZOOM
        latitude = point.latitude if point else MAP_START[0]
        longitude = point.longitude if point else MAP_START[1]
        margin = max(page.width or 800, page.height or 700) / (256 * 2 ** zoom)
        mercator = log(tan(pi / 4 + radians(max(-85, min(85, latitude))) / 2))
        north = degrees(atan(sinh(min(pi, mercator + pi * margin))))
        south = degrees(atan(sinh(max(-pi, mercator - pi * margin))))
        west, east = longitude - 180 * margin, longitude + 180 * margin
        if west < -180 or east > 180:
            west, east = -180, 180
        try:
            credit = await asyncio.to_thread(map_provider.google_credit, google_credentials,
                                             ceil(zoom), north, south, east, west)
        except Exception:
            if initial:
                osm_basemap()
                notify("Google Maps no está disponible. Mostrando OpenStreetMap.", "#775019")
        else:
            set_basemap("google", google_url, f"Google Maps · {credit}", zoom=22)
        page.update()

    async def track_camera(event):
        nonlocal last_camera, credit_job
        last_camera = event.camera
        if active_provider != "google" or event.event_type not in {
            fm.MapEventType.MOVE_END, fm.MapEventType.FLING_ANIMATION_END,
            fm.MapEventType.DOUBLE_TAP_ZOOM_END, fm.MapEventType.SCROLL_WHEEL_ZOOM,
            fm.MapEventType.NON_ROTATED_SIZE_CHANGE,
        }:
            return
        if credit_job and not credit_job.done():
            credit_job.cancel()
        credit_job = asyncio.create_task(update_google_credit(last_camera))

    async def load_provider():
        nonlocal google_url, google_credentials
        try:
            google_url, google_credentials = await asyncio.to_thread(map_provider.google_tiles)
        except Exception:
            osm_basemap()
            notify("Google Maps no está disponible. Mostrando OpenStreetMap.", "#775019")
            return
        await update_google_credit(last_camera, initial=True)
        if active_provider == "google":
            globe.on_event = track_camera
            page.update()

    def button(label, callback, icon=None):
        return ft.Button(label, on_click=callback, icon=icon, height=40,
                         style=ft.ButtonStyle(bgcolor="#17604A", color="#FFFFFF",
                                              shape=ft.RoundedRectangleBorder(radius=10)))

    async def locate(event=None):
        if drawing:
            notify("Cierra o cancela el dibujo antes de cambiar de lugar.", "#775019")
            return
        nonlocal position_revision, locating, gps_position
        if locating:
            return
        if page.web and not web_location_allowed(page.url):
            show_map()
            notify("Activa HTTPS para usar el GPS o marca la parcela en el mapa.", "#775019")
            return
        locating = True
        gps_position = None
        gps_accuracy.circles = []
        analyze_location.visible = False
        position_revision += 1
        revision = position_revision
        location_button.disabled = True
        location_button.tooltip = "Buscando ubicación…"
        notify("Buscando ubicación… Si aparece el permiso, elige Permitir.", dismiss=False)
        try:
            # The browser requests permission through getCurrentPosition itself.
            if event is not None and not page.web:
                await asyncio.wait_for(geo.request_permission(), timeout=12)
            configuration = gps.GeolocatorWebConfiguration(
                accuracy=gps.GeolocatorPositionAccuracy.HIGH,
                time_limit=ft.Duration(seconds=LOCATION_TIMEOUT), maximum_age=ft.Duration(seconds=0),
            ) if page.web else None
            timeout = LOCATION_TIMEOUT + 1 if page.web else 23
            position = await asyncio.wait_for(geo.get_current_position(configuration), timeout=timeout)
        except TimeoutError:
            if revision == position_revision:
                show_map()
                notify("El navegador no entregó una ubicación a tiempo. Reintenta o usa Buscar.",
                       "#775019", dismiss=False)
            return
        except Exception as error:
            logging.getLogger(__name__).warning("Geolocalización: %s", error)
            if revision == position_revision:
                show_map()
                reason = str(error).lower()
                if "denied" in reason or "permission" in reason:
                    message = "Permite la ubicación en el navegador y en el dispositivo, y reintenta."
                elif "timeout" in reason or "timed out" in reason:
                    message = "El navegador no entregó una ubicación a tiempo. Reintenta o usa Buscar."
                else:
                    message = "El navegador no pudo obtener tu ubicación. Reintenta o usa Buscar."
                notify(message, "#775019", dismiss=False)
            return
        finally:
            locating = False
            location_button.disabled = False
            location_button.tooltip = "Mi ubicación"
            page.update()
        if revision == position_revision:
            if not valid_position(position):
                show_map()
                notify("El dispositivo no entregó coordenadas válidas. Intenta de nuevo o busca tu zona.",
                       "#775019", dismiss=False)
                return
            point = fm.MapLatitudeLongitude(position.latitude, position.longitude)
            approximate = position.accuracy > PARCEL_LOCATION_ACCURACY
            gps_accuracy.circles = [fm.CircleMarker(
                radius=max(1, position.accuracy), use_radius_in_meter=True,
                coordinates=point,
                color="#334D9DF0", border_color="#4D9DF0", border_stroke_width=2,
            )]
            if not approximate:
                gps_position = (point, position.accuracy)
                gps_accuracy.circles.append(fm.CircleMarker(
                    radius=5, coordinates=point, color="#1767A8",
                    border_color="#FFFFFF", border_stroke_width=2,
                ))
                analyze_location.visible = True
            show_map()
            source = "Área aproximada del navegador" if approximate else "Ubicación del dispositivo"
            guidance = ("Usa Buscar para ir a tu localidad y marca la parcela en el mapa."
                        if approximate else "Confirma el punto azul o selecciona tu parcela.")
            notify(f"{source} · margen ±{position.accuracy:.0f} m. {guidance}",
                   "#775019" if approximate else "#146247", dismiss=False)
            await focus_map(point, location_zoom(position.accuracy))

    async def focus_map(point, zoom):
        try:
            await asyncio.wait_for(globe.move_to(point, zoom=zoom), timeout=3)
        except TimeoutError:
            logging.getLogger(__name__).debug("El mapa no confirmó el cambio de cámara")

    async def confirm_location(_):
        if gps_position and not locating:
            point, accuracy = gps_position
            await select(point.latitude, point.longitude, f"Ubicación confirmada · margen ±{accuracy:.0f} m",
                         zoom=location_zoom(accuracy))

    async def manual(_):
        try:
            latitude, longitude = float(lat.value), float(lon.value)
        except ValueError:
            status.value = "Introduce latitud y longitud numéricas."
            page.update()
            return
        await select(latitude, longitude)

    async def select(latitude, longitude, name="Parcela seleccionada", *, zoom=None):
        nonlocal version, position_revision, scene_request, climate_job, scene_job, selection_key, provider_focus
        if drawing:
            notify("Cierra o cancela el dibujo antes de cambiar de lugar.", "#775019")
            return
        position_revision += 1
        try:
            first, last = date.fromisoformat(start.value), date.fromisoformat(end.value)
            if not (-85 <= latitude <= 85 and -180 <= longitude <= 180):
                raise ValueError
            if not 0 <= (last - first).days <= 366:
                raise ValueError
        except ValueError:
            status.value = "Revisa las coordenadas y las fechas. El período máximo es de un año."
            page.update()
            return
        key = (round(latitude, 5), round(longitude, 5), first, last)
        if name == "Parcela seleccionada" and key == selection_key and climate_job and not climate_job.done():
            return
        selection_key = key
        for job in (climate_job, scene_job):
            if job and not job.done():
                job.cancel()
        version += 1
        current = version
        point = fm.MapLatitudeLongitude(latitude, longitude)
        provider_focus = point
        show_map()
        drawer.visible = True
        reopen_analysis.visible = False
        panel.content = climate
        highlight_tab("Clima")
        lat.value, lon.value = f"{latitude:.5f}", f"{longitude:.5f}"
        coords.value = f"{name} · {lat.value}, {lon.value}"
        analyze_location.visible = False
        toast.visible = False
        status.value = ""
        marker.markers = [fm.Marker(coordinates=point, content=ft.Icon(ft.Icons.LOCATION_ON, color="#D55334", size=36))]
        climate.controls = [ft.ProgressBar(), ft.Text("Consultando NASA POWER…")]
        satellite.controls = [ft.Text("Abre ECOSTRESS para consultar las escenas de esta parcela.")]
        page.update()
        async def focus():
            try:
                target_zoom = zoom if zoom is not None else 13 if name != "Parcela seleccionada" else None
                await focus_map(point, target_zoom)
            except Exception:
                pass

        async def update(panel, fetch, render):
            try:
                data = await asyncio.to_thread(fetch, latitude, longitude, first, last)
                if current == version:
                    panel.controls = render(data)
            except Exception as error:
                logging.getLogger(__name__).warning("NASA %s: %s", fetch.__name__, type(error).__name__)
                if current == version:
                    async def retry(_):
                        if current != version:
                            return
                        panel.controls = [ft.ProgressBar(), ft.Text("Consultando NASA…")]
                        panel.update()
                        await update(panel, fetch, render)

                    panel.controls = [
                        ft.Text("NASA no respondió. Puedes reintentar esta consulta."),
                        ft.TextButton("Reintentar", on_click=retry),
                    ]
            if current == version:
                page.update()

        async def load_scenes():
            satellite.controls = [ft.ProgressBar(), ft.Text("Buscando escenas en NASA Earthdata…")]
            page.update()
            await update(satellite, nasa.scenes, scene_panel)

        scene_request = load_scenes
        async def load_climate():
            # A second tap can replace this selection before starting network work.
            await asyncio.sleep(.22)
            await asyncio.gather(focus(), update(climate, nasa.climate, climate_panel))

        climate_job = asyncio.create_task(load_climate())

    def climate_panel(data):
        def display_units(code):
            raw = data.get("parameters", {}).get(code, {}).get("units", "")
            return {"C": "°C", "MJ/m^2/day": "MJ/m²/día",
                    "mm/day": "mm/día", "kW-hr/m^2/day": "kWh/m²/día"}.get(raw, raw)

        daily = {code: nasa.daily(data, code) for code in nasa.METRICS}
        rainfall = daily["PRECTOTCORR"]
        tiles = []
        for code, label in nasa.METRICS.items():
            values = [value for _, value in daily[code] if value is not None]
            units = display_units(code)
            if code == "PRECTOTCORR":
                label, units, aggregate = "Lluvia acumulada", "mm", sum
            else:
                aggregate = {"T2M_MIN": min, "T2M_MAX": max}.get(code, mean)
            text = f"{aggregate(values):.2f} {units}" if values else "Sin datos"
            tiles.append(card(label, text))
        valid_rain = sum(value is not None for _, value in rainfall)
        tiles.append(card("Racha seca (< 1 mm/día)", f"{nasa.dry_spell(rainfall)} días" if valid_rain else "Sin datos"))
        detail = ft.Text(selectable=True, color="#173B2D", weight=ft.FontWeight.W_600)
        scale = ft.Text(size=12, color="#3F6354")
        chart = cv.Canvas(height=122)
        chart_width = 240
        day_slider = ft.Slider(min=0, max=1, value=0)
        metric = ft.Dropdown(
            label="Explorar serie diaria", value="T2M",
            options=[ft.DropdownOption(key=key, text=label) for key, label in nasa.METRICS.items()],
        )

        def show_day(_=None):
            values = daily[metric.value]
            day_slider.max = max(1, len(values) - 1)
            day_slider.divisions = max(1, len(values) - 1)
            day_slider.disabled = len(values) <= 1
            day_slider.value = min(int(day_slider.value), max(0, len(values) - 1))
            if not values:
                detail.value = "Sin datos para esta variable."
                scale.value = ""
                chart.shapes = []
                return
            day, value = values[int(day_slider.value)]
            units = display_units(metric.value)
            detail.value = f"{day} UTC · " + ("Sin dato" if value is None else f"{value:.2f} {units}")
            valid = [v for _, v in values if v is not None]
            if not valid:
                scale.value = ""
                chart.shapes = []
                return
            low, high = min(valid), max(valid)
            scale.value = f"Rango observado · {low:.2f} a {high:.2f} {units}"
            x = lambda i: 8 + (chart_width - 16) * i / max(1, len(values) - 1)
            y = lambda v: 108 - 94 * (v - low) / (high - low) if high != low else 61
            line = ft.Paint(color="#238365", stroke_width=2)
            grid = ft.Paint(color="#D1E5D9", stroke_width=1)
            chart.shapes = [cv.Line(8, h, chart_width - 8, h, grid) for h in (14, 61, 108)]
            for i in range(1, len(values)):
                a, b = values[i - 1][1], values[i][1]
                if a is not None and b is not None and (values[i][0] - values[i - 1][0]).days == 1:
                    chart.shapes.append(cv.Line(x(i - 1), y(a), x(i), y(b), line))
            if value is not None:
                chart.shapes.append(cv.Circle(x(int(day_slider.value)), y(value), 4, ft.Paint(color="#D65F3A")))

        def chart_resize(event):
            nonlocal chart_width
            if abs(chart_width - event.width) < 1:
                return
            chart_width = max(17, event.width)
            show_day()
            chart.update()

        chart.on_resize = chart_resize
        def changed(event):
            show_day(event)
            page.update()

        metric.on_select = changed
        day_slider.on_change_end = changed
        show_day()
        return [
            ft.Text(f"NASA POWER · resolución regional · {valid_rain} días con datos de lluvia"),
            ft.ResponsiveRow(tiles), metric,
            ft.Container(content=ft.Column([chart, scale], spacing=4,
                         horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
                         padding=10, bgcolor="#EDF6F1", border_radius=12),
            day_slider, detail,
        ]

    def scene_panel(entries):
        if not entries:
            return [ft.Text("NASA Earthdata no encontró escenas para este punto y período.")]
        controls = [ft.Text(f"{len(entries)} escenas candidatas · ECO_L2T_LSTE v002. Verifica nubes y calidad.")]
        for scene in entries:
            title = scene.get("title", "")
            # NASA CMR distinguishes browse imagery from protected science files.
            browse_urls = [
                link["href"] for link in scene.get("links", [])
                if link.get("rel", "").endswith("/browse#") and link.get("href", "").startswith("https://")
                and link["href"].lower().endswith((".jpg", ".jpeg", ".png"))
            ]
            thermal = next((url for url in browse_urls if url.lower().endswith("_lst.jpeg")), None)
            browse = thermal or next(iter(browse_urls), None)
            children = [
                ft.Text(scene.get("time_start", "")[:16].replace("T", " ") + " UTC", weight=ft.FontWeight.BOLD),
                ft.Text(title, selectable=True),
                ft.TextButton("Abrir registro de NASA Earthdata",
                              url=f"https://cmr.earthdata.nasa.gov/search/concepts/{scene['id']}.umm_json"),
            ]
            if browse:
                preview = ft.Container()

                async def toggle_preview(event, target=preview, image_url=browse):
                    trigger = event.control
                    if target.content is None or isinstance(target.content, ft.Text):
                        target.content = ft.ProgressBar()
                        trigger.disabled = True
                        page.update()
                        try:
                            image = await asyncio.to_thread(nasa.preview_image, image_url)
                            target.content = ft.Image(src=image, height=180, fit=ft.BoxFit.CONTAIN,
                                                      error_content=ft.Text("Imagen no compatible."))
                            trigger.content = "Ocultar imagen"
                        except Exception:
                            target.content = ft.Text("NASA no entregó esta miniatura. Abre el registro para revisarla.")
                            trigger.content = "Reintentar imagen"
                        finally:
                            trigger.disabled = False
                    else:
                        target.content = None
                        trigger.content = "Ver imagen NASA"
                    page.update()

                children.extend([ft.TextButton("Ver imagen NASA", on_click=toggle_preview), preview])
            controls.append(ft.Container(content=ft.Column(children), padding=12, bgcolor="#F3F7F3", border_radius=12))
        return controls

    def card(label, value):
        return ft.Container(
            col=6, bgcolor="#E4F2E9", border_radius=12, padding=12,
            content=ft.Column([ft.Text(label, size=12, color="#305B47"),
                              ft.Text(value, size=20, color="#123C2A", weight=ft.FontWeight.BOLD)]),
        )

    rotation = ft.Column()
    priority = ft.Dropdown(
        label="Prioridad", value="water",
        options=[ft.DropdownOption(key=k, text=v) for k, v in
                 [("water", "Ahorrar agua"), ("soil", "Cubrir el suelo"), ("equal", "Equilibrar")]],
    )
    options = []
    for label in ("Rotación actual", "Alternativa A", "Alternativa B"):
        sequence = ft.TextField(label=label, hint_text="Cultivo → cultivo de cobertura")
        levels = [ft.DropdownOption(key=str(i), text=name) for i, name in enumerate(("Baja", "Media", "Alta"))]
        water = ft.Dropdown(label="Demanda de agua", width=168, options=levels)
        cover = ft.Dropdown(label="Cobertura del suelo", width=168,
                            options=[ft.DropdownOption(key=item.key, text=item.text) for item in levels])
        options.append((sequence, water, cover))
        rotation.controls.extend([sequence, ft.Row([water, cover], wrap=True)])
    result = ft.Text(selectable=True)

    def compare(_):
        if any(not name.value.strip() or water.value is None or cover.value is None for name, water, cover in options):
            result.value = "Completa las secuencias, la demanda y la cobertura de las tres opciones."
        else:
            w, c = {"water": (2, 1), "soil": (1, 2), "equal": (1, 1)}[priority.value]
            ranked = sorted(
                [((2 - int(water.value)) * w + int(cover.value) * c, name.value.strip())
                 for name, water, cover in options], key=lambda item: item[0], reverse=True,
            )
            lines = [f"{name} · {score} puntos" for score, name in ranked]
            result.value = "\n".join(lines + [f"Peso del agua: {w}. Peso de la cobertura: {c}."])
        page.update()

    rotation.controls = [
        ft.Text("Evalúa la demanda de agua y la cobertura con los datos de tu finca."),
        priority, *rotation.controls, button("Comparar rotaciones", compare), result,
    ]
    parcel_status = ft.Text("Dibuja el perímetro tocando el mapa. El área es aproximada.")
    draw_tools = ft.Container(visible=False)
    draw_hint = ft.Text(size=12, color="#285344")

    def pick_vertex(index):
        def pick(_):
            nonlocal selected_vertex
            if drawing:
                selected_vertex = index
                update_boundary()
        return pick

    def update_boundary():
        outline.polylines = [fm.PolylineMarker(coordinates=vertices.copy(), color="#17604A",
                                              stroke_width=4)] if drawing and len(vertices) >= 2 else []
        finish_button.disabled = len({(p.latitude, p.longitude) for p in vertices}) < 3
        undo_button.disabled = not vertices
        handles.markers = [
            fm.Marker(coordinates=point, width=34, height=34, content=ft.Container(
                on_click=pick_vertex(i - 1), bgcolor="#B65C22" if selected_vertex == i - 1 else "#155840",
                border_radius=17, alignment=ft.Alignment.CENTER,
                content=ft.Text(str(i), size=12, color="#FFFFFF"),
            )) for i, point in enumerate(vertices, 1)
        ]
        if drawing:
            boundary.polygons = []
            if len(vertices) >= 3:
                show_boundary(vertices)
        parcel_status.value = f"{len(vertices)} vértices. Toca el mapa para añadir otro." if drawing else "Dibuja el perímetro tocando el mapa."
        draw_hint.value = (
            f"Toca la nueva posición del vértice {selected_vertex + 1}."
            if selected_vertex is not None else
            f"{len(vertices)} vértices. Toca el mapa para añadir. Toca un número para moverlo."
        )
        page.update()

    async def draw_parcel(_):
        nonlocal drawing, selected_vertex, position_revision
        if drawing:
            return
        if locating:
            return
        position_revision += 1
        toast.visible = False
        drawing = True
        analyze_location.visible = False
        location_button.disabled = True
        selected_vertex = None
        draw_tools.visible = True
        vertices[:] = saved_vertices
        boundary.polygons = []
        drawer.visible = False
        reopen_analysis.visible = False
        show_map()
        update_boundary()
        center = saved_vertices[0] if saved_vertices else provider_focus
        if center is None and gps_position:
            center = gps_position[0]
        if center is not None:
            await focus_map(center, 16)
        elif (last_camera.zoom if last_camera else globe.initial_zoom) < PARCEL_ZOOM:
            draw_hint.value = "Toca la zona para acercarte. Luego marca al menos tres vértices."
            page.update()

    def undo(_):
        nonlocal selected_vertex
        if drawing and vertices:
            selected_vertex = None
            vertices.pop()
            update_boundary()

    def cancel_draw(_):
        nonlocal drawing, selected_vertex
        drawing = False
        location_button.disabled = False
        analyze_location.visible = gps_position is not None
        selected_vertex = None
        draw_tools.visible = False
        vertices.clear()
        handles.markers = []
        boundary.polygons = []
        if saved_vertices:
            show_boundary(saved_vertices)
        drawer.visible = True
        update_boundary()
        if saved_vertices:
            parcel_status.value = "Edición cancelada. Se conservó el perímetro anterior."
            page.update()

    def show_boundary(points):
        boundary.polygons = [fm.PolygonMarker(coordinates=points.copy(), color="#4434D399",
                           border_color="#34D399", border_stroke_width=3)]

    def finish_parcel(_):
        nonlocal drawing, selected_vertex
        if not drawing or len({(p.latitude, p.longitude) for p in vertices}) < 3:
            draw_hint.value = "Añade al menos tres vértices distintos."
            page.update()
            return
        pairs = list(zip(vertices, vertices[1:] + vertices[:1]))
        area = abs(sum(
            radians((b.longitude - a.longitude + 180) % 360 - 180)
            * (sin(radians(a.latitude)) + sin(radians(b.latitude))) for a, b in pairs
        )) * 6371008.8 ** 2 / 2
        if area < 1:
            draw_hint.value = "El contorno no encierra área suficiente. Ajusta los vértices."
            page.update()
            return
        drawing = False
        location_button.disabled = False
        selected_vertex = None
        draw_tools.visible = False
        outline.polylines = []
        handles.markers = []
        saved_vertices[:] = vertices
        show_boundary(saved_vertices)
        drawer.visible = True
        panel.content = parcel
        highlight_tab("Parcela")
        parcel_status.value = f"Área aproximada: {area / 10000:.3f} ha · {len(vertices)} vértices."
        page.update()

    parcel = ft.Column([
        ft.Text("Delimitar parcela", size=20, weight=ft.FontWeight.BOLD), parcel_status,
        button("Dibujar o editar parcela", draw_parcel),
        ft.Text("Clima y ECOSTRESS se consultan para el punto seleccionado."),
    ])
    panels = {"Clima": climate, "ECOSTRESS": satellite, "Parcela": parcel, "Rotaciones": rotation}
    panel = ft.Container(content=climate, bgcolor="#FFFFFF", padding=18, border_radius=16)

    def highlight_tab(name):
        for tab in tabs:
            active = tab.data == name
            tab.style = ft.ButtonStyle(bgcolor="#17604A" if active else "#E3EFE8",
                                       color="#FFFFFF" if active else "#214D3A")

    async def show_panel(event):
        nonlocal scene_request, scene_job
        panel.content = panels[event.control.data]
        highlight_tab(event.control.data)
        page.update()
        if event.control.data == "ECOSTRESS" and scene_request:
            fetch_scenes, scene_request = scene_request, None
            scene_job = asyncio.create_task(fetch_scenes())

    location_button = ft.Button(
        "Mi ubicación", on_click=locate, tooltip="Mi ubicación",
        style=ft.ButtonStyle(bgcolor="#E8F6FF", color="#123250"),
        visible=not use_3d,
    )
    analyze_location = button("Analizar ubicación", confirm_location)
    analyze_location.visible = False
    async def select_from_globe(latitude, longitude):
        await select(latitude, longitude, "Punto seleccionado en el globo")

    welcome = GlobeView(on_point=select_from_globe)
    web_globe = fwv.WebView(url=globe_url, expand=True) if use_3d else None
    map_area = ft.Container(top=0, bottom=0, left=0, right=0, visible=False)
    welcome_layer = ft.Container(content=web_globe or welcome, top=0, bottom=0, left=0, right=0)

    def toggle_globe(_):
        welcome_layer.content = welcome if welcome_layer.content is web_globe else web_globe
        location_button.visible = welcome_layer.content is welcome
        page.update()

    def show_map():
        nonlocal provider_started
        if map_area.content is None:
            map_area.content = globe
        if not provider_started:
            provider_started = True
            if map_provider.google_requested():
                attribution.value = "Cargando Google Maps…"
                asyncio.create_task(load_provider())
            else:
                osm_basemap()
        welcome_layer.visible = False
        map_area.visible = True
        attribution.visible = True
        map_credit.visible = True
        map_toolbar.visible = True
        explore_button.visible = False
        location_button.visible = True
        globe_switch.visible = False

    def return_to_globe(_):
        if drawing:
            cancel_draw(None)
        drawer.visible = False
        map_area.visible = False
        map_credit.visible = False
        map_toolbar.visible = False
        explore_button.visible = True
        location_button.visible = welcome_layer.content is not web_globe or not use_3d
        welcome_layer.visible = True
        globe_switch.visible = use_3d
        page.update()

    def open_drawer(_):
        drawer.visible = True
        reopen_analysis.visible = False
        page.update()

    def close_drawer(_):
        drawer.visible = False
        reopen_analysis.visible = True
        page.update()

    attribution.visible = False
    for field in (lat, lon, start, end):
        field.col = 6
        field.width = None
    tabs = [ft.TextButton(name, data=name, on_click=show_panel) for name in panels]
    highlight_tab("Clima")
    content_scroll = ft.Column([
        panel,
        ft.ExpansionTile(title=ft.Text("Coordenadas y fechas"), controls=[
            ft.Container(padding=ft.Padding.symmetric(vertical=10), content=ft.Column([
                ft.ResponsiveRow([lat, lon, start, end], spacing=8, run_spacing=12),
                button("Aplicar cambios", manual), status,
            ])),
        ]),
    ], scroll=ft.ScrollMode.AUTO, expand=True, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
    drawer = ft.Container(
        width=420, visible=False, bgcolor="#F3F7F3", padding=16,
        content=ft.Column([
            ft.Row([ft.Text("Análisis de parcela", size=22, weight=ft.FontWeight.BOLD),
                    ft.IconButton(ft.Icons.CLOSE, tooltip="Cerrar panel", on_click=close_drawer)],
                   alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            coords,
            ft.Row(tabs, wrap=True, spacing=6, run_spacing=6),
            content_scroll,
        ], expand=True),
    )
    map_credit = ft.Container(left=12, bottom=10, right=92, visible=False,
                              alignment=ft.Alignment.CENTER_LEFT, content=ft.Container(
                                  bgcolor="#18382D", padding=7, border_radius=8, content=attribution,
                              ))
    draw_tools.left, draw_tools.bottom = 12, 88
    draw_tools.padding, draw_tools.bgcolor, draw_tools.border_radius = 12, "#FFFFFF", 12
    finish_button = button("Guardar contorno", finish_parcel)
    undo_button = ft.IconButton(ft.Icons.UNDO, tooltip="Quitar último vértice", on_click=undo)
    draw_tools.content = ft.Column([ft.Text("Dibujar parcela", weight=ft.FontWeight.BOLD), draw_hint, ft.Row([
        undo_button,
        finish_button,
        ft.TextButton("Cancelar", on_click=cancel_draw),
    ], wrap=True)], tight=True, spacing=2)
    toast = ft.Container(top=65, right=12, width=300, padding=12, border_radius=12,
                         content=location_status, visible=False, ignore_interactions=True)
    map_stack = ft.Stack([
        ft.Image(src="space.svg", left=0, right=0, top=0, bottom=0, fit=ft.BoxFit.COVER),
        welcome_layer, map_area,
        map_credit,
        draw_tools,
        ft.Container(right=12, bottom=42, content=ft.Row(
            [analyze_location, location_button], spacing=6, tight=True,
        )),
        toast,
    ], expand=True)
    globe_switch = ft.Container(
        left=12, bottom=72, visible=use_3d,
        content=ft.IconButton(ft.Icons.LAYERS_OUTLINED, tooltip="Cambiar vista del globo",
                              on_click=toggle_globe, bgcolor="#152940", icon_color="#E5F3FF"),
    )
    map_stack.controls.insert(-1, globe_switch)
    map_surface = ft.Container(content=map_stack, bgcolor="#030610", expand=True)
    compact_layout = None

    def resize(_=None):
        nonlocal compact_layout
        if not provider_started:
            globe.initial_zoom = max(MAP_START_ZOOM, ceil(log(max(256, page.width or 800) / 256, 2)))
        compact = bool(page.width and page.width < 760)
        draw_tools.width = min(390, max(200, (page.width or 800) - 24))
        drawer.width = None if compact else min(460, max(330, (page.width or 1100) * .35))
        if page.web:
            width = page.width or 800
            header_view.height = 138 if width <= 510 else 112 if width <= 680 else 73
        drawer.height = min(500, (page.height or 700) * .57) if compact else None
        toast.width = min(300, max(140, (page.width or 800) - 24))
        if compact != compact_layout:
            layout_type = ft.Column if compact else ft.Row
            root.content = layout_type([map_surface, drawer], expand=True, spacing=0)
            compact_layout = compact
        welcome.resize_globe(page.width or 800, page.height or 700)
        page.update()

    root = ft.Container(expand=True)
    place_input = ft.TextField(hint_text="Buscar ciudad o localidad", prefix_icon=ft.Icons.SEARCH,
                               border=ft.OutlineInputBorder(border_radius=24),
                               dense=True, autofocus=True, expand=True)
    place_results = ft.Column(scroll=ft.ScrollMode.AUTO, height=230)
    search_version = 0
    search_token = ""
    search_credit = ft.Text(size=12)

    async def search_places(_, immediate=False):
        nonlocal search_version, search_token
        search_version += 1
        current_search = search_version
        query = place_input.value.strip()
        if len(query) < 2:
            place_results.controls = []
            page.update()
            return
        if not immediate:
            await asyncio.sleep(.35)
            if current_search != search_version:
                return
        place_results.controls = [ft.Text("Buscando lugares…")]
        page.update()
        using_google = active_provider == "google" and google_search_enabled()
        try:
            if using_google:
                matches = await asyncio.to_thread(google_places, query, search_token)
            else:
                matches = await asyncio.to_thread(find_places, query)
        except Exception:
            matches = None
            if using_google:
                try:
                    matches = await asyncio.to_thread(find_places, query)
                    using_google = False
                except Exception:
                    pass
        if current_search != search_version:
            return
        search_credit.value = "Google Maps" if using_google else "Open-Meteo · GeoNames"
        place_results.controls = []
        for place in matches or []:
            name = place["name"]
            context = ", ".join(dict.fromkeys(place[key] for key in ("admin1", "country")
                                              if place.get(key) and place[key] != name))
            label = ", ".join(filter(None, (name, context)))

            async def choose_place(event, result=place, title=label):
                nonlocal search_version, search_token
                search_version += 1
                choice = search_version
                if "place_id" in result:
                    search_token = str(uuid4())
                    place_results.controls = [ft.ProgressBar(), ft.Text("Abriendo lugar…")]
                    page.update()
                    try:
                        latitude, longitude = await asyncio.to_thread(
                            google_location, result["place_id"], result["session_token"],
                        )
                    except Exception:
                        if choice == search_version:
                            place_results.controls = [ft.Text("Google no pudo abrir este lugar. Busca de nuevo.")]
                            page.update()
                        return
                else:
                    latitude, longitude = result["latitude"], result["longitude"]
                if choice != search_version:
                    return
                page.pop_dialog()
                await select(latitude, longitude, title)

            place_results.controls.append(ft.ListTile(
                leading=ft.Icon(ft.Icons.LOCATION_ON_OUTLINED, color="#17604A"),
                title=ft.Text(name, weight=ft.FontWeight.W_600),
                subtitle=ft.Text(context) if context else None,
                on_click=choose_place,
            ))
        if not matches:
            place_results.controls = [ft.Text("La búsqueda no respondió. Reintenta." if matches is None else "No hay coincidencias. Prueba con el país.")]
        page.update()

    def close_search(_):
        nonlocal search_version
        search_version += 1
        page.pop_dialog()

    async def submit_search(event):
        await search_places(event, immediate=True)

    place_input.on_change = search_places
    place_input.on_submit = submit_search
    search_dialog = ft.AlertDialog(
        modal=True, title=ft.Text("Buscar zona"),
        content=ft.Column([
            ft.Row([place_input]),
            place_results, search_credit,
        ], width=365, tight=True),
        actions=[ft.TextButton("Cerrar", on_click=close_search)],
    )

    def open_search(_):
        nonlocal search_token
        if drawing:
            notify("Cierra o cancela el dibujo antes de buscar otro lugar.", "#775019")
            return
        search_token = str(uuid4())
        place_input.value = ""
        using_google = active_provider == "google" and google_search_enabled()
        place_input.hint_text = "Busca una dirección o un lugar" if using_google else "Buscar ciudad o localidad"
        place_results.controls = []
        search_credit.value = "Google Maps" if using_google else "Open-Meteo · GeoNames"
        page.show_dialog(search_dialog)

    map_stack.controls.insert(-1, ft.Container(right=14, top=14, content=ft.Row([
        ft.Button("Dibujar", icon=ft.Icons.EDIT_LOCATION_ALT_OUTLINED, on_click=draw_parcel,
                  style=ft.ButtonStyle(bgcolor="#E8F6FF", color="#123250")),
        ft.Button("Buscar", icon=ft.Icons.SEARCH, on_click=open_search,
                  style=ft.ButtonStyle(bgcolor="#E8F6FF", color="#123250")),
    ], spacing=6)))
    reopen_analysis = ft.IconButton(ft.Icons.ANALYTICS_OUTLINED, tooltip="Abrir análisis",
                                    on_click=open_drawer, icon_color="#DCF5E9")
    if page.web:
        map_stack.controls.append(ft.Container(left=14, top=14, content=reopen_analysis))
        reopen_analysis.bgcolor = "#E8F6FF"
        reopen_analysis.icon_color = "#123250"

    def explore_map(_):
        show_map()
        page.update()

    explore_button = ft.TextButton("Mapa", icon=ft.Icons.MAP_OUTLINED,
                                   url=map_url if page.web else None,
                                   on_click=None if page.web else explore_map,
                                   style=ft.ButtonStyle(color="#DCF5E9"))
    map_toolbar = ft.Row([
            ft.IconButton(ft.Icons.HOME_OUTLINED if page.web else ft.Icons.PUBLIC,
                          tooltip="Inicio" if page.web else "Volver al globo",
                          url=home_url if page.web else None,
                          on_click=None if page.web else return_to_globe,
                          icon_color="#DCF5E9"),
            *([] if page.web else [reopen_analysis]),
        ], spacing=0, visible=False)
    toolbar = ft.Container(bgcolor="#081b18", padding=ft.Padding.symmetric(horizontal=16, vertical=6), content=ft.Row([
            ft.Image(src="landing/logo.webp", width=30, height=30, border_radius=6, visible=not page.web),
            ft.Text("Parcela" if page.web else "TerraSprout", color="#FFFFFF", size=20, weight=ft.FontWeight.BOLD, expand=True,
                    max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
            explore_button,
            map_toolbar,
        ], spacing=2))
    landing = fwv.WebView(url=project_url, expand=True, visible=False) if page.web else None
    if page.web:
        header_view = fwv.WebView(url=f"{chrome_url}?vista=header&pagina=mapa", height=73)
        page.add(header_view, root, landing)
    else:
        page.add(toolbar, root)
    page.on_resize = resize
    resize()
    last_point_route = None

    async def open_point_route(route):
        nonlocal last_point_route
        if not route or route == last_point_route:
            return
        point = page.query.to_dict.get("punto")
        if not point:
            last_point_route = None
            return
        try:
            latitude, longitude = map(float, point.split(","))
        except ValueError:
            return
        if not (-85 <= latitude <= 85 and -180 <= longitude <= 180):
            return
        last_point_route = route
        await select(latitude, longitude, "Coordenadas de la parcela")

    if page.web:
        async def open_route(route):
            path = urlsplit(route or "").path.rstrip("/")
            show_landing = path not in {"/mapa", "/globo"} and not page.query.to_dict.get("punto")
            landing.visible = show_landing
            header_view.visible = root.visible = not show_landing
            section = page.query.to_dict.get("seccion")
            if show_landing and section in {"video", "proyecto", "equipo"}:
                landing.url = f"{project_url}#{section}"
            if path in {"/mapa", "/globo"}:
                show_map()
            page.update()
            action = page.query.to_dict.get("accion")
            if path == "/mapa" and action == "ubicacion":
                await locate()
                return
            if path == "/mapa" and action == "buscar":
                open_search(None)
            await open_point_route(route)
            if path == "/mapa" and action == "dibujar":
                await draw_parcel(None)

        async def route_changed(event):
            await open_route(event.route)

        page.on_route_change = route_changed
        await open_route(page.route)



if __name__ == "__main__":
    ft.run(main, assets_dir="assets", route_url_strategy=ft.RouteUrlStrategy.PATH)
