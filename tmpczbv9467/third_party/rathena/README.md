# Referência do formato GRF

`nrobot/grf_header.py` é uma adaptação Python do algoritmo de cabeçalho padrão
GRF descrito por `src/common/des.cpp` do rAthena. A fonte de referência original
está preservada como `des.cpp`, com a licença do projeto em `LICENCE` (GPL v3).

Fontes consultadas:

- https://github.com/rathena/rathena/blob/master/src/common/des.cpp
- https://github.com/rathena/rathena/blob/master/src/common/grfio.cpp
- https://github.com/rathena/rathena/blob/master/LICENSE

Alterações desta adaptação: permutações de bits em inteiros Python, tabelas
equivalentes e aplicação apenas aos primeiros vinte blocos de oito bytes para
entradas com flag de cabeçalho padrão. Não implementa recursos de codificação
customizada nem acesso a memória/processos do jogo.

REDE-54: grfio.cpp preservado como referencia GPL v3. A adaptacao tambem implementa ciclos de blocos DES e desintercalacao/substituicao da variante mista padrao GRF.
