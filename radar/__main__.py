"""Linha de comando do painel.

    python -m radar painel                         abre o painel no navegador (http://127.0.0.1:8787)
    python -m radar painel --banco D:/radar.db     com o banco em outro lugar
    python -m radar painel --rede                  também no celular, na mesma rede Wi-Fi
    python -m radar capas                          baixa agora as capas e fotos que faltam
    python -m radar site                           grava o painel sem servidor em site/, para o GitHub Pages
"""
import argparse
import os
from pathlib import Path


def main(argv=None) -> None:
    comum = argparse.ArgumentParser(add_help=False)
    comum.add_argument("--dados", help="Pasta de dados do Radar, com radar.db, capas/ e stories/ (padrão: ./data).")
    comum.add_argument("--banco", help="Caminho do radar.db (padrão: <dados>/radar.db).")
    analisador = argparse.ArgumentParser(prog="python -m radar", description="Painel do Radar de Reputação da Energisa.")
    comandos = analisador.add_subparsers(dest="comando", required=True)
    painel = comandos.add_parser("painel", parents=[comum], help="Abre o painel no navegador.")
    painel.add_argument("--porta", type=int, default=8787)
    painel.add_argument("--rede", action="store_true", help="Abre também para outros aparelhos da mesma rede.")
    painel.add_argument("--sem-abrir", action="store_true", help="Não abre o navegador sozinho.")
    capas = comandos.add_parser("capas", parents=[comum], help="Baixa agora as capas e fotos que faltam.")
    capas.add_argument("--limite", type=int, default=2000, help="Máximo de imagens nesta rodada.")
    site = comandos.add_parser("site", parents=[comum], help="Grava o painel sem servidor, para o GitHub Pages.")
    site.add_argument("--saida", default="site", help="Pasta do site (padrão: site/).")
    args = analisador.parse_args(argv)

    # Antes de importar o painel: a configuração lê estas variáveis na importação.
    if args.dados:
        os.environ["RADAR_DADOS"] = args.dados
    if args.banco:
        os.environ["RADAR_DB"] = args.banco
    from . import capas as capas_mod, db, painel as painel_mod

    if args.comando == "painel":
        painel_mod.servir(args.porta, rede=args.rede, abrir=not args.sem_abrir)
        return
    con = db.conectar_leitura()
    if args.comando == "site":
        from . import estatico
        feito = estatico.exportar(con, Path(args.saida))
        print(f"Site em {Path(args.saida).resolve()}: {feito['mencoes']} menções, {feito['contas']} contas, "
              f"{len(feito['com_capa'])} capas, {len(feito['com_foto'])} fotos e {len(feito['midias'])} mídias de "
              f"stories; {feito['arquivos']} arquivos de dados ({feito['bytes'] / 1e6:.1f} MB). Para ver antes de "
              f"publicar: python -m http.server --directory {args.saida}")
        return
    feitos = capas_mod.rodada(con, limite=args.limite)
    apagadas = capas_mod.limpar(con)
    print(f"{feitos['baixadas']} imagens baixadas, {feitos['falhas']} falharam (endereço vencido ou sem rede), "
          f"{feitos['faltam']} ficaram para a próxima; {apagadas} capas de posts fora da Energisa apagadas. "
          f"Pasta: {capas_mod.PASTA}")


if __name__ == "__main__":
    main()
