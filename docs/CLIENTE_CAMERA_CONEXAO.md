# Conexao e variante de camera/tremor

Em 05/11/2026 a inicializacao do relay foi bloqueada porque o SHA256 completo do NRO.exe mudou apos uma alteracao visual de camera/tremor. O registro da tentativa em `logs/relay/20261105-143027-114385-painel/saida_relay.log` confirma que a falha ocorreu antes de abrir os listeners.

A copia local `GRFs personalizadas/Backup camera e tremor 20261105-141801/NRO.exe` corresponde exatamente ao SHA256 original da tabela de pacotes. Comparacao byte a byte com o executavel atual identificou apenas seis bytes alterados, nos offsets de arquivo `0x10a900..0x10a902` e `0x10a920..0x10a922`. O trecho de registro dos 627 pacotes, entre os enderecos virtuais `0x41b226` e `0x4206af`, permaneceu identico.

A variante verificada foi incluida em `compatible_executables` de `data/rede/tamanhos_cliente.json`, com SHA256 e registro das alteracoes. O leitor aceita o original e essa variante especifica. Executaveis desconhecidos continuam recusados. Nao basta trocar o SHA256 para aceitar uma futura versao: uma mudanca de protocolo requer nova verificacao.

Essa compatibilidade permite iniciar a conexao com o cliente visual modificado; nao valida a integracao grafica RCX. O executavel e as DLLs do jogo nao foram alterados por esta correcao.
