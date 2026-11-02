import os
import time
import argparse
from datetime import datetime
from pipeline_ia import carregar_env, executar_pipeline


def iniciar_monitoramento(intervalo_horas: float):
    print("=" * 60)
    print("🤖 AI JOB HUNTER — MONITORAMENTO CONTÍNUO + WHATSAPP")
    print(f"⏱️  Frequência configurada: a cada {intervalo_horas} hora(s)")
    print("=" * 60)

    ciclo = 1
    while True:
        agora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        print(f"\n🚀 [Ciclo #{ciclo} - {agora}] Iniciando varredura automática de vagas...")
        try:
            executar_pipeline(notificar_whatsapp=True)
        except Exception as e:
            print(f"⚠️ Erro durante o Ciclo #{ciclo}: {e}")

        segundos = int(intervalo_horas * 3600)
        print(f"\n💤 Ciclo #{ciclo} finalizado! Próxima execução em {intervalo_horas}h ({segundos}s). Pressione Ctrl+C para encerrar.")
        ciclo += 1
        time.sleep(segundos)


if __name__ == "__main__":
    carregar_env()
    parser = argparse.ArgumentParser(description="Automação contínua de vagas com envio para WhatsApp")
    parser.add_argument(
        "--horas",
        type=float,
        default=float(os.environ.get("INTERVALO_HORAS", "4")),
        help="Intervalo em horas entre cada busca de vagas (padrão: 4)",
    )
    args = parser.parse_args()
    iniciar_monitoramento(args.horas)

