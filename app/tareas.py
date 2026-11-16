"""Tareas diarias: respaldo de la base de datos y revisión de alarmas de vencimiento."""
import logging
import re
import smtplib
import sqlite3
from email.message import EmailMessage
from pathlib import Path
from typing import List, Optional

from . import config, db, servicios

registro = logging.getLogger("proveedores.tareas")

PATRON_RESPALDO = re.compile(r"^proveedores-\d{8}-\d{6}\.db$")


def listar_respaldos(carpeta: Path) -> List[Path]:
    """Respaldos existentes, del más reciente al más antiguo."""
    carpeta = Path(carpeta)
    if not carpeta.is_dir():
        return []
    return sorted((a for a in carpeta.iterdir() if a.is_file() and PATRON_RESPALDO.match(a.name)), reverse=True)


def respaldar(ruta_bd: Path = None, carpeta: Path = None, conservar: int = None) -> Path:
    """Copia consistente de la base (API de respaldo de SQLite) y borra los respaldos que sobran."""
    cfg = config.actual
    ruta_bd = Path(ruta_bd or cfg.ruta_bd)
    carpeta = Path(carpeta or cfg.ruta_respaldos)
    conservar = conservar or cfg.respaldos_conservar
    carpeta.mkdir(parents=True, exist_ok=True)
    destino = carpeta / f"proveedores-{config.ahora():%Y%m%d-%H%M%S}.db"
    origen = sqlite3.connect(str(ruta_bd))
    try:
        copia = sqlite3.connect(str(destino))
        try:
            origen.backup(copia)
        except Exception:
            copia.close()
            destino.unlink(missing_ok=True)  # no dejar un respaldo a medias que desplace a uno bueno
            raise
        finally:
            copia.close()
    finally:
        origen.close()
    for viejo in listar_respaldos(carpeta)[conservar:]:
        try:
            viejo.unlink()
        except OSError:
            registro.warning("No se pudo borrar el respaldo antiguo %s", viejo.name)
    return destino


def texto_alarmas(grupos: dict, dias: int) -> str:
    lineas = []
    for clave, titulo in (
        ("vencidas", "VENCIDAS"),
        ("hoy", "VENCEN HOY"),
        ("proximas", f"VENCEN EN LOS PRÓXIMOS {dias} DÍAS"),
    ):
        facturas = grupos[clave]
        lineas.append(f"{titulo}: {len(facturas)}" + (f" ({servicios.totales(facturas)})" if facturas else ""))
        for f in facturas:
            lineas.append(
                f"  - {f.proveedor.nombre} · factura {f.numero} · vence {f.vencimiento:%d/%m/%Y} · "
                f"{f.moneda} {f.valor:,.2f}"
            )
        lineas.append("")
    return "\n".join(lineas)


def enviar_correo(asunto: str, cuerpo: str) -> None:
    cfg = config.actual
    mensaje = EmailMessage()
    mensaje["Subject"] = asunto
    mensaje["From"] = cfg.correo_remitente or cfg.smtp_usuario
    mensaje["To"] = ", ".join(cfg.correo_destinatarios)
    mensaje.set_content(cuerpo)
    with smtplib.SMTP(cfg.smtp_host, cfg.smtp_puerto, timeout=30) as servidor:
        if cfg.smtp_tls:
            servidor.starttls()
        if cfg.smtp_usuario:
            servidor.login(cfg.smtp_usuario, cfg.smtp_clave)
        servidor.send_message(mensaje)


def revisar_alarmas() -> Optional[dict]:
    """Cuenta lo vencido y lo próximo a vencer; envía el resumen por correo solo si CORREO_ACTIVO=true."""
    if db.SessionLocal is None or not config.actual.facturacion_activa:
        return None
    cfg = config.actual
    sesion = db.SessionLocal()
    try:
        dias = servicios.dias_aviso(sesion)
        grupos = servicios.facturas_por_vencer(sesion, config.hoy(), dias)
        conteo = {clave: len(lista) for clave, lista in grupos.items()}
        registro.info("Alarmas: %s vencidas, %s vencen hoy, %s próximas", conteo["vencidas"], conteo["hoy"], conteo["proximas"])
        enviado = "no (envío por correo apagado)"
        if cfg.correo_activo:
            if not (cfg.smtp_host and cfg.correo_destinatarios):
                enviado = "no (faltan SMTP_HOST o CORREO_DESTINATARIOS)"
            elif not any(conteo.values()):
                enviado = "no (nada por vencer)"
            else:
                try:
                    enviar_correo(
                        f"Pagos a proveedores: {conteo['vencidas']} vencidos, {conteo['hoy']} vencen hoy",
                        texto_alarmas(grupos, dias),
                    )
                    enviado = "sí"
                except Exception as error:  # el correo nunca debe tumbar la tarea diaria
                    registro.exception("No se pudo enviar el correo de alarmas")
                    enviado = f"no (error: {type(error).__name__})"
        servicios.cfg_guardar(
            sesion,
            "ultima_revision",
            f"{config.ahora():%d/%m/%Y %H:%M} — {conteo['vencidas']} vencidas, {conteo['hoy']} vencen hoy, "
            f"{conteo['proximas']} próximas; correo enviado: {enviado}",
        )
        sesion.commit()
        return conteo
    finally:
        sesion.close()


def tarea_diaria() -> None:
    try:
        destino = respaldar()
        registro.info("Respaldo creado: %s", destino.name)
    except Exception:
        registro.exception("Falló el respaldo diario")
    try:
        revisar_alarmas()
    except Exception:
        registro.exception("Falló la revisión de alarmas")


def iniciar_programador():
    """Programa la tarea diaria dentro de la misma app. Devuelve el programador (o None si está apagado)."""
    cfg = config.actual
    if not cfg.tareas_activas:
        return None
    from apscheduler.schedulers.background import BackgroundScheduler

    try:
        hora, minuto = (int(x) for x in cfg.hora_tarea.split(":"))
        if not (0 <= hora <= 23 and 0 <= minuto <= 59):
            raise ValueError
    except ValueError:
        registro.warning("HORA_TAREA_DIARIA no es válida (%s); se usa 07:00", cfg.hora_tarea)
        hora, minuto = 7, 0
    try:
        programador = BackgroundScheduler(timezone=cfg.zona)
    except Exception:
        registro.warning("ZONA_HORARIA no es válida (%s); se usa la hora del sistema", cfg.zona)
        programador = BackgroundScheduler()
    programador.add_job(
        tarea_diaria,
        "cron",  # como texto, para que use la zona horaria del programador
        hour=hora,
        minute=minuto,
        id="tarea_diaria",
        replace_existing=True,
        misfire_grace_time=6 * 3600,
        coalesce=True,
    )
    programador.start()
    registro.info("Tarea diaria programada a las %02d:%02d (%s)", hora, minuto, cfg.zona)
    return programador
