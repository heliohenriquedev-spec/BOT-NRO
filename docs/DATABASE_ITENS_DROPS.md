# Database de itens e drops

Na aba **Monstros**, abra **Database de itens e drops**. Um duplo clique em um monstro abre a consulta filtrada por seu ID de espécie. A coleta ocorre enquanto o personagem está conectado pelo bot, inclusive com a caça pausada. Reabra o painel atualizado para carregar esta implementação.

São armazenados ID e nome do item, quantidade, mapa e horário UTC da observação. O ID do objeto no chão serve para evitar registros repetidos enquanto ele continua visível; ele é diferente do ID do tipo de item. Os vínculos guardam a espécie e o nome recebido do monstro, pois uma aparência pode ser usada por monstros diferentes.

Os pacotes de itens no chão não informam qual monstro originou o item. Quando um item novo aparece até 1,5 segundo de uma morte observada e a até 3 células da posição estimada do monstro, o bot registra uma **associação candidata**. Pode haver várias candidatas para o mesmo item. Proximidade não prova origem: outros jogadores podem matar monstros ou jogar itens no chão. Monstros identificados como invocações, jogadores e aparições excluídas da base não geram esses vínculos.

Itens que já estavam no chão são registrados sem inferir origem. Itens recebidos no inventário também ficam sem vínculo, pois podem vir de compra, troca, missão ou coleta automática do servidor. A ausência de aparição no chão impede atribuir esse recebimento a uma morte. Desaparecimento de item não prova coleta pelo personagem.

Use **Confirmar vínculo conferido no jogo** apenas após conferir a associação. Isso marca uma revisão humana e descarta vínculos concorrentes daquela observação; não representa confirmação fornecida pelo servidor. A busca aceita item, ID, monstro e mapa. **Exportar consulta JSON** exporta os registros exibidos, com limite de 500 grupos. Contagens representam observações locais, não uma tabela completa nem porcentagens oficiais de drop.

## Drops informados pelo servidor (@mi)

Como os pacotes de chão não dizem a origem e itens raros podem nunca cair, o bot pergunta ao servidor com o mesmo comando que o jogador digitaria: `@mi ID_do_monstro`. Cada monstro confirmado que aparece no mapa é consultado **uma vez** (as espécies já salvas não são repetidas), com no mínimo 4 segundos entre comandos e só com o personagem no mapa e os envios liberados. O botão **Consultar @mi agora**, na aba **Drops do servidor (@mi)**, repete a consulta de qualquer ID.

Somente as linhas que o servidor envia ao próprio personagem logo após o comando são lidas; falas de outros jogadores ("Nome : texto") e anúncios globais nunca são guardados. A ficha aceita nomes simples, `Nome [slots]`, `Nome (ID)` e links de item (`<ITEML>`), de onde sai o ID do item. Quando só vem o nome, o ID é procurado no catálogo de nomes do cliente; se não houver correspondência, aparece `?`. Itens de MVP ficam marcados como **MVP**. A coluna **Vistos** mostra quantos drops daquele item foram associados ao monstro nas observações.

Se duas consultas seguidas ficarem sem resposta ou com um formato não reconhecido, as consultas automáticas param até o relay ser reaberto (o botão continua funcionando). Toda resposta fica em `respostas_mi.jsonl`, na pasta da sessão do relay, para ajustar o leitor a outro formato. As chances são as que o servidor informa para o personagem, não observações locais.

Os registros ficam em `data/database/observacoes.sqlite3`, preservados pelo atualizador e excluídos da publicação. O catálogo de nomes `data/recursos/itens.json` acompanha o código e é independente das GRFs visuais do usuário. Não há coleta automática de itens nem mudanças no combate nesta funcionalidade.

Referência dos formatos de chão: [rAthena, clif_getareachar_item e clif_dropflooritem](https://github.com/rathena/rathena/blob/master/src/map/clif.cpp), conferidos contra os tamanhos dos pacotes do cliente local. Os formatos observados são 009D, 009E e 00A1; não se presume suporte a outros formatos sem validação.
