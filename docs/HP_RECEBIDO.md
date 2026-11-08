# HP recebido de jogadores

O relay registra passivamente as barras de HP entregues pelo servidor em
`logs/relay/<sessao>/hp_recebido.json` e em `received_player_hp` no estado da sessao.
Nao envia consultas de HP nem altera permissoes, grupo ou guilda.

- `0106`, 10 bytes: ID do jogador e dois valores de 16 bits da barra de HP.
- `02E0`, 34 bytes: ID, nome e os dois valores da barra no formato antigo de BG.
- O formato textual `HP: atual/maximo` em `0195` continua sendo tratado separadamente.

Valores de 16 bits podem representar uma escala percentual usada pelo servidor para
personagens com muito HP. Por isso o diagnostico guarda `hp_units`, `max_hp_units`,
`hp_percent` e `absolute_hp_confirmed: false`; nao os apresenta como HP absoluto.
Cada observacao tem horario, mapa e idade. `recent` fica falso apos 10 segundos sem
atualizacao. A observacao anterior e apagada ao trocar de mapa/conexao.

O diagnostico inclui a guilda recebida e a participacao real no grupo (pacotes de PT).
O texto de rank do NRO no campo de nome de grupo nao comprova participacao na PT.
A existencia de HP em um pacote nao comprova que o mesmo dado seja enviado para
todos os jogadores; a ausencia em uma coleta curta tambem nao comprova que nunca
seja enviado. Para comparar, observe pessoas da guilda/grupo e de fora durante
mudancas reais de HP e com os vinculos recebidos.

Nas capturas anteriores foram encontrados 11.665 registros de `0106` nas 16 sessoes
recentes examinadas. Antes desta leitura, apareciam como `other` e os valores nao
eram preservados; nao e possivel recupera-los desses registros resumidos.

Referencia de layout (nao e o codigo do servidor NRO):
[rAthena: estruturas de pacotes](https://github.com/rathena/rathena/blob/master/src/map/packets_struct.hpp)
e [envio da barra de HP](https://github.com/rathena/rathena/blob/master/src/map/clif.cpp).

## Verificacao local em 08/11/2026

Na sessao iniciada em 00:09, o cliente recebeu barras `0106` de um jogador com o mesmo vinculo textual de guilda/vila do personagem, fora da PT identificada. A barra mudou de 27/100 para 33/100. Na janela adicional de 30 segundos havia nove IDs de jogadores observados, mas so aquele ID teve HP recebido. Outros jogadores, incluindo pessoas com guilda/vila diferente, nao tiveram HP entregue nessa janela. Isso nao prova disponibilidade para qualquer jogador nem ausencia definitiva fora da guilda: seria necessario observar atualizacoes reais de HP desses jogadores. O diagnostico detalhado permanece nos logs locais, sem nomes de jogadores neste documento.
