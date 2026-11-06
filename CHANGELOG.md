# Changelog do BOT NRO

Novidades de cada atualização. O que ainda não foi publicado fica em "Próxima atualização".

## Próxima atualização

## 2026.11.06.4 (06/11/2026)

- Caca pela database: consultas @showmobs repetem a cada 60 s e podem antecipar a busca apos 10 s sem alvo. Uma rodada sem resposta nao desativa novas consultas; tentativas antecipadas respeitam um intervalo minimo.
- Combate: confirmacoes de stun, sono e silencio nao contam como dano concluido. O controlador avalia os alvos visiveis dentro do raio antes de iniciar dano, e buffs com condicao de proximidade respeitam essa regra.
- Habilidades: recargas informadas pelo servidor prevalecem sobre atrasos temporarios de nova tentativa de buff.
- Rotas: caches de navegacao ficam associados ao mapa de colisao correto, evitando reaproveitar caminhos calculados para outro mapa.

- Caca pela database: ao chegar ao mapa de destino, as configuracoes de combate por mapa controlam alvos, prioridades e habilidades; a database continua controlando viagem e @showmobs. Se a montaria configurada nao estiver disponivel para o personagem, a rota segue a pe.
- Combate: uma habilidade pronta tem prioridade sobre o ataque basico; ataques basicos continuam intercalados nos intervalos entre habilidades.

## 2026.11.06.3 (06/11/2026)

- Combate: buffs de uso em si respeitam recargas informadas pelo servidor; recusas consecutivas aumentam a espera entre novas tentativas para evitar reenvios continuos.
- Navegação: a área prevista da Venom Dust agora usa a cruz de cinco células em vez de um quadrado maior.
- Comportamento por mapa: o motor permite aproximar de alvos elegíveis dentro de um raio limitado, sem perseguir além dele.

- Navegacao: duas opcoes independentes controlam evitar celulas de efeitos de terreno ja ativos e prever areas hostis quando a conjuracao comeca; ambos os bloqueios sao revalidados antes de enviar movimento.



- Rota de quests: configuracao para limitar de 1 a 20 tentativas de retorno ao ponto de salvamento enquanto o personagem permanece morto (padrao 4).


- Corrigida parada ao ver monstro inelegivel: a validacao de patrulha agora usa os mesmos alvos elegiveis do combate. Em area livre, adquire e aproxima de um alvo visivel; nao o descarta ao entrar no raio proximo. Atacantes a distancia continuam sendo defendidos. Regras de excecao do perfil nao bloqueiam a patrulha.
- Primeira ofensiva em alcance ganha o turno antes de renovacoes opcionais de buff, reduzindo o atraso para iniciar combate sem ignorar SP, recarga ou alcance. Adicionadas verificacoes de regressao para a selecao e a aproximacao de alvos.



- Perfis de combate agora aceitam prioridades de monstros, controle de stun/sono/silencio confirmado pelos pacotes, buffs persistentes e ofensivas intercaladas com ataques basicos, sem modificar a patrulha.

- Nova aba Comportamento por mapa: importa e exporta perfis JSON validados, aplica regras de combate por mapa, mantendo a patrulha normal e restaura as gerais ao sair. Perfis podem ser desativados e ficam suspensos durante quests.

- Morte na caça: nova opção (aba Rota de quests) para, ao morrer, voltar ao ponto de retorno, curar no NPC de cura e voltar ao mapa onde estava pelas rotas, na caça comum, na caça pela database e na fila de quests; a caça comum é retomada com as mesmas configurações. A conversa com o NPC de cura é gravada uma vez ("Gravar cura") e pode ser conferida com "Testar cura".
- BG e cura: estando já no mapa do NPC, o bot faz a conversa gravada (antes considerava a viagem concluída e não falava com ele).
- Combate: desligar o "Intercalar ataque básico" não liga mais o kite sozinho em configurações antigas; o kite só funciona com a opção de kite marcada.
- Caça pela database: opção "Usar @showmobs" por monstro (na janela de loot do monstro e na coluna @showmobs da janela "Caçar"); só os monstros marcados são procurados com @showmobs, e a escolha fica salva.
- @showmobs (caça pela database e quests): se não houver resposta ou nenhum grupo alcançável, o bot para de repetir o @showmobs naquele mapa e percorre o mapa inteiro em uma caminhada linear, como nos mapas de corredor. O @showmobs volta quando a caça ou a fila é iniciada de novo.

## 2026.11.06.2 (06/11/2026)

- Conexão: um NRO.exe de outra versão (por exemplo, atualizado pelo atualizador do jogo) é aceito quando a tabela de pacotes dele é idêntica à conhecida, conferida byte a byte; se a tabela mudou, o bot avisa e mostra o código da versão. A mensagem também diferencia "NRO.exe não encontrado na pasta escolhida".

## 2026.11.06.1 (06/11/2026)

- Portais: ao atravessar um portal, o bot registra para qual mapa ele leva; o portal mais próximo de onde você aparece fica registrado como a volta para o mapa anterior. Os destinos vão para todos na atualização.
- Rotas automáticas: cada portal em que você entra e cada NPC que troca de mapa (retorno no Kakashi, acesso e Sala VIP etc.) alimentam sozinhos o mapa de caminhos do bot, com a conversa e as opções escolhidas. A fila de quests, a entrada na BG e a caça pela database usam esses caminhos aprendidos junto com os percursos gravados; na janela "Caçar", esses mapas aparecem como "caminho aprendido pelos portais".
- BG: partindo de outro mapa, o bot vai até o NPC da BG e faz a conversa gravada (antes só chegava ao mapa).
- Portais: corrigido o registro automático das passagens entre mapas, que não gravava nenhum portal; agora vale também quando você clica longe e o personagem caminha até o portal. O arquivo data/mapas/portais_destinos.json é criado ao abrir o bot e recebe cada portal atravessado.
- Portais: um portal que leva a outro mapa deixa de ser tratado como portal interno (havia um falso no Kakashi, 52,2), assim que a passagem é confirmada.
- Database: novo botão "Caçar" na aba Monstros, na ficha de um monstro e na lista de quem dropa um item. Escolha o mapa, marque os monstros e a prioridade; o bot vai até lá pelo percurso gravado e caça com suas configurações de combate.
- Tela do jogo: removida a lista "Últimos registros de jogadores ocultos/fora de visão".
- Minimapa: NPCs aparecem como losangos ciano, com o nome ao passar o mouse; os nomes ficam salvos por mapa.
- Minimapa: coordenadas do personagem embaixo do minimapa, fixo ou solto.
- Minimapa: monstros encontrados pelo @showmobs aparecem como X rosa, com o nome ao passar o mouse.
- Minimapa: portais mostram o mapa de destino ao passar o mouse; jogadores escondidos ficam só com o marcador, sem texto.
- Caça: corrigido o travamento ao andar com o @showmobs (o nome de cada marca era lido do disco a cada atualização).
- Caça com @showmobs: o destino soma os monstros de todas as espécies consultadas e pesa o tamanho do grupo pela distância a pé até ele; um grupo distante só vence se for bem maior, e o destino só muda quando o novo é claramente melhor. Antes ia sempre para o maior grupo do mapa, atravessando o mapa de um lado para o outro.
- Caça pela database: metas por mortes, por minutos caçando no mapa ou por quantidade de um item juntado; termina na primeira atingida. Sem metas, caça até você parar.
- Caça pela database: sprite de cada monstro na janela "Caçar"; clicando, aparecem os loots com "Pegar este" (@alootid), "Pegar todos" e ligar/desligar @autoloot.
- BG: nova aba para entrar na BG 3x3, 4x4 ou 5x5. Grave o NPC de cada BG uma vez (andar, NPC e opções). As mensagens de erro e de sucesso são gravadas uma vez, em qualquer NPC, e valem para todas. Os botões "Entrar na 3x3", "4x4" e "5x5" falam com o NPC daquela BG e tentam de novo até a inscrição dar certo; aí param sozinhos.
- BG: botões "Gravar mensagem de erro" e "Gravar mensagem de sucesso": clique e fale com o NPC no jogo; a fala dele vira a mensagem usada para saber se a inscrição deu certo.
- Caça: "Ignorar até (atacando você)" agora conta só os monstros que não são alvo; os monstros caçados que revidam não fazem mais o bot atacar todos os outros.
- Minimapa e contador da quest: voltam a aceitar cliques e arraste com a Database, a janela Caçar ou outra janela do bot aberta.
- RCX: área da Ira de Thor (e das outras magias em área) aparece mesmo quando o servidor manda a unidade no chão antes do aviso da magia; antes ficava só um ponto.
- RCX: Pântano dos Mortos e as outras magias de área com unidade própria (Pneuma, Vulcão, Dilúvio, Gravidade etc.) mostram a área inteira quando o servidor manda só a unidade central.

## 2026.11.05.4 (05/11/2026)

- Notas de atualização: cada versão publicada passa a trazer a lista de novidades, também postada no canal de atualizações do Discord.
- RCX: pintura de habilidades no chao do jogo com canal direto de baixa latencia, cores, simbolos e opacidade personalizaveis por habilidade.
- RCX: previas de mira e conjuracao organizadas logo abaixo da aparencia do efeito, com ativacao independente e preferencias salvas imediatamente.
- RCX: suporte a habilidades de area usadas em si, como Desperado, e visualizacao configuravel da area de ativacao das armadilhas.
- RCX: tentativas de uso sem resposta nao deixam area temporaria; falhas e cancelamentos removem a previa correspondente.
- RCX: raio e formato ativam a personalizacao automaticamente; ID obtido da habilidade e bloqueado para edicao.
- RCX: preferencias preservadas entre paineis abertos, botao Salvar agora e confirmacao do arquivo utilizado.
- Quests: patrulha ativada na etapa de caca, retomada da exploracao apos destino sem progresso e observacao de jogadores suspensa durante os percursos.
- Quests: rotas concluidas comecam desmarcadas; ao marca-las novamente, e possivel repetir viagem e caca sem apagar o historico diario.
- Quests: corrigida a viagem isolada para usar os acessos compartilhados e conectar o mapa atual ao inicio do percurso, inclusive em outros personagens e computadores.
- Quests: editor otimizado com um indice de monstros carregado uma vez, evitando centenas de leituras repetidas da base.
- Atualizacao: confirmacao com espera minima de cinco segundos antes de baixar e reiniciar o painel.
- Quests: @showmobs soma os monstros dos tipos consultados, deduplica marcas e escolhe uma concentracao acessivel; a caca continua durante o trajeto.
- Changelog: registro das alteracoes pendentes revisado e orientacao do projeto para registrar cada pedido implementado antes da proxima publicacao.
- Database: todas as observacoes de monstros, mortes, itens, associacoes e drops do servidor passam a acompanhar as atualizacoes, com backup e mesclagem sem duplicar as coletas dos jogadores.
- Quests: isolamento dos testes corrigido para que gravacoes de validacao nunca usem o arquivo de rotas do usuario.
