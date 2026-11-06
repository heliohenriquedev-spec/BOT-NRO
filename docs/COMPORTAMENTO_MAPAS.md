# Comportamento por mapa

Na aba **Comportamento por mapa**, clique em **Importar perfil** e selecione o JSON preparado para o mapa. Revise as regras exibidas. Ativar / desativar controla a aplicacao automatica. Exportar permite compartilhar o arquivo com outro jogador; importar novamente substitui o perfil daquele mapa apos confirmacao.

Nao precisa reiniciar: o relay verifica os perfis a cada meio segundo. Importar pode mudar o combate durante a caca; prefira pausar antes de importar. O perfil nao inicia a caca nem abre conexao por conta propria. Ao sair do mapa, desativar ou remover o perfil, voltam as configuracoes gerais. Em quests, o perfil fica suspenso e a rota continua no controle.

Exemplos: `exemplos/comportamentos/moc_fild01.json` e `exemplos/comportamentos/ra_fild03.json`. Eles nao sao instalados nem ativados automaticamente. Ambos ficam dentro da pasta `exemplos` do pacote de atualizacao e podem ser importados por cada jogador como ponto de partida, depois editados/exportados individualmente. O arquivo usa nome interno do mapa (com ou sem .gat), schema, nome, descricao, enabled, settings e, no schema 2, regras de combate declarativas. Apenas regras declaradas sao alteradas. Os limites sao os mesmos do painel.

Regras disponiveis em settings:

A patrulha e a exploracao permanecem com o funcionamento normal; o perfil nao as altera.
- Combate: skills, auto_attacks, melee_approach, kite, ignore_attackers, switch_distance, switch_saving, switch_ratio_percent.

As habilidades e monstros continuam sendo os configurados no personagem. Este formato inicial nao grava dialogos, caminhos personalizados, scripts, credenciais ou regras de quest. Nao executa codigo do arquivo. Perfis ficam em data/rede/comportamentos_mapas.json, protegidos de sobrescrita pelo atualizador.

Para solicitar um perfil, descreva: nome interno do mapa, combate corpo a corpo ou a distancia, autoataque, habilidades ligadas/desligadas, preferencias de troca de alvo. Por exemplo: "Em moc_fild01, usar minhas habilidades sem autoataque e manter distancia do monstro". Regras novas que ainda nao estejam no formato exigem ampliar o motor antes de importar; descricao livre nao e executada como instrucao.

## Perfil ra_fild03 (schema 2)

Arquivo pronto para importar: `exemplos/comportamentos/ra_fild03.json`.

1. Pause a caca. Se o painel estava aberto antes desta implementacao, encerre a conexao e reabra o painel uma vez para carregar o novo codigo.
2. Na aba Comportamento por mapa, importe ra_fild03.json. Confira as regras exibidas.
3. Conecte o personagem e inicie a caca em ra_fild03. A patrulha continua com suas configuracoes normais.

O perfil define:

- Ordem de morte: Ninkame (1315), Jounin (1634), Salamandra (1831), Doki (1177). Os IDs sao os sprites registrados para este mapa; a base local tambem chama o sprite 1831 de Camaleon.
- Dentro de 9 celulas, Jounin sem silencio tem prioridade de controle sobre o dano. Shikumi (179) primeiro, Fukai Yasumi (182) se o stun nao entrou, Jigyaku no Chakra (76) apos stun/sono ou como alternativa se os outros estiverem indisponiveis. Confirma pelo estado real recebido; uma confirmacao de execucao da habilidade nao prova que o status entrou.
- Doki passivo recebe silencio antes de qualquer dano do bot. Se ja foi atacado e perde silencio, tenta stun/sono, aplica silencio e retoma o dano. Se surgir Ninkame ou Jounin, controla o Doki proximo antes de abandona-lo quando possivel; depois retorna conforme a prioridade. Removidos/mortos saem da fila; monstros fora da visibilidade nao podem ser controlados.
- Buffs: Concentrar Chakra nos Pes (29, efeito 12) e Shinkirou no Genjutsu (532, efeito 207). Vinculos encontrados no registro local de buffs. A renovacao usa a leitura dos efeitos, nao um temporizador arbitrario.
- Dano: Kunai (524), Shuriken (523), TsuutenKyaku (62), intercalando autoataques quando dentro do alcance. A rotacao existente continua validando SP, municao/equipamento, alcance, obstaculos, recarga recebida e intervalo global. Nao envia rajadas para ignorar recargas.

Somente habilidades aprendidas no personagem sao habilitadas; usa o nivel maximo aprendido recebido do servidor para cada habilidade deste perfil. Outras habilidades ofensivas ficam fora desta rotacao. Se uma habilidade de controle nao existir no personagem, tenta as alternativas aprendidas. Doki nunca e liberado para dano sem silencio confirmado; imunidade ou falta de silencio pode impedi-lo de atacar esse monstro.

O silencio e reconhecido pelo bit de health state, stun/sono pelo body state. A referencia do protocolo esta nas [definicoes de status do rAthena](https://github.com/rathena/rathena/blob/master/src/map/status.hpp). Os pacotes sao a autoridade; nao ha duracao confiavel de silencio neste perfil, portanto renova quando a remocao chega, sem presumir antecipacao. Falha de stun tem uma curta janela de confirmacao antes de tentar sono, respeitando o intervalo global.

Como nos perfis simples, quests continuam com suas proprias regras. Seguidores de grupo e foco em jogador tambem conservam seu controle de alvo, em vez de aplicar a selecao independente deste perfil. O perfil nao altera a patrulha, nao inicia a caca sozinho e nao foi ativado automaticamente no seu personagem.


### Reacao rapida e emergencia de ra_fild03

O perfil ativo usa **quatro ou mais Jounin** (1634), cada um a ate nove celulas, para ativar a regra de emergencia. O controle comum de Jounin tambem comeca em nove celulas.

A reacao suspende dano e preparacoes comuns: usa Selo de Mao: Coelho (500) tres vezes, contando somente respostas de execucao bem-sucedida para o proprio personagem. Pacote enviado, resposta recusada ou resposta duplicada nao contam como um uso adicional. Depois aguarda Fukai Kemuri (668) aparecer com nivel positivo no servidor (ela pode estar no nivel 0 antes dos selos), conjura em si e inicia a fuga. A confirmacao prova execucao, nao garante que todos os inimigos dormiram.

A fuga usa o mapa de colisao para aumentar distancia dos Jounin envolvidos, sem escolher celulas bloqueadas. Nao usa um raio fixo para declarar que saiu da tela: termina quando os alvos nao aparecem mais na visibilidade recebida. Se a sequencia nao for confirmada em 12 segundos, retira por seguranca; sem colisao valida nao envia movimento cego. As regras normais de presenca, pausa manual e conexao continuam valendo. A patrulha nao foi alterada.

O controle comum tem janela de confirmacao de 150 ms, ante os 500 ms anteriores. Pode tomar o proximo turno apos o intervalo global mesmo com dano anterior ainda sem resposta; nao ignora recarga, SP ou alcance. Habilidades de controle disponiveis precedem buffs na rotacao de emergencia de alvo. Falha de aplicar status nao e usada como prova de que o intervalo global deve aumentar.

O perfil usa o nivel maximo aprendido, inclusive Shikumi, Fukai, silencio e Imagem Falsa. A duracao real dos status continua dependendo das regras do servidor e do alvo; o bot nao prolonga os efeitos.

Imagem Falsa / Shinkirou (532) aguarda ao menos 20 segundos depois de uma execucao confirmada. Remocao antecipada do efeito e troca de mapa nao liberam tentativa antes da recarga. Ao expirar, retoma tentativas normais se o efeito estiver ausente; uma tentativa recusada nao inicia mais 20 segundos de espera. Uma recarga maior recebida do servidor tambem e respeitada.


### Selecao reativa, excecoes e ofensivas adicionais

O exemplo atualizado agora usa `engagement`: distancia maxima de **9 celulas** e ataque/conjuracao direcionado ao proprio personagem observado nos ultimos **10 segundos**. Receber um ataque contra outro jogador muda esse registro; morte, remocao e troca de mapa o descartam. Conjuracao em si ou no chao nao prova troca de alvo. A lista de prioridade decide entre os monstros que passam por esses filtros.

O cliente nao recebe necessariamente o alvo interno da IA antes de seu primeiro ataque ou conjuracao: aparicao, proximidade e caminhar na sua direcao nao sao tratados como prova de que o monstro esta mirando voce. Um monstro passivo, inclusive Doki, fica fora da selecao normal enquanto nao houver essa evidencia. A regra defensiva de tres Jounin proximos continua independente, como configurada anteriormente.

Para Salamandra (1831), `no_basic_attack_species` bloqueia autoataques e `no_chase_species` impede perseguicoes longas. A excecao `approach_species` deixa adquirir a Salamandra visivel dentro do raio de combate (9 celulas neste exemplo) e aproximar ate o alcance das ofensivas aprendidas; nao persegue uma Salamandra alem desse raio. A verificacao de parede continua ativa, e habilidades precisam estar aprendidas, disponiveis e no alcance antes do envio.

Dai Senkou (357) mantem o buff pelo efeito **105**, vinculo ja registrado localmente. Sogu: Baku Ryusei (775) e um buff em si; o perfil usa a duracao de 15 s descrita no cliente e respeita a recarga explicita recebida do servidor. Se vier apenas recusa, o bot aumenta progressivamente a espera entre tentativas. O cliente informa alcance 9, mas a habilidade nao entra na selecao de dano. Rasengan (370, alcance recebido 2) e permitida apenas para Ninkame (1315) e Salamandra (1831), via `offensive_species`. Rasengan nao autoriza perseguir Salamandra nem ultrapassar seu alcance.

`burst.enabled` ativa a rajada ofensiva; `burst.interval` esta em **0.05 s**, limitado a uma tentativa ofensiva por esse intervalo. Essa e a modalidade de rajada do bot: pode repetir uma ofensiva sem aguardar o dano da tentativa anterior, mas conserva SP, alvo permitido, alcance, recargas conhecidas, municao e conjuracao em andamento. Stun, sono, silencio, buffs e a sequencia de Coelho/Kemuri nao entram nessa repeticao de dano. Autoataques continuam intercalados nos demais monstros; Salamandra fica sem eles.

### Namekuji somente em area livre

`idle_summon` habilita Kuchiyose: Namekuji (729) no nivel maximo aprendido, somente com HP confirmado **abaixo de 60%** e quando nao ha **nenhum monstro visivel a ate 4 celulas**, inclusive tipos nao selecionados para caca, monstros passivos ou atacando outros jogadores. Se HP/HP maximo nao foram recebidos, nao invoca. Invocacoes de jogadores identificadas e o proprio personagem nao contam como monstros hostis. A verificacao e repetida sob a trava de envio: se um monstro aparecer entre planejar e enviar, a invocacao e cancelada.

A recarga local do exemplo e **30 segundos**, preservando o valor encontrado na configuracao existente do painel; ela nao foi inferida como duracao da criatura. Recarga maior informada pelo servidor prevalece. O campo `idle_summon.cooldown` pode ser ajustado no JSON conforme a recarga real. A invocacao usa uma celula caminhavel proxima do personagem e exige mapa de colisao valido. A fila existente acompanha confirmacao, criatura e termino; esta invocacao nunca suspende ofensivas para tentar invocar ao lado de um monstro.

Neste PC, o perfil salvo foi sincronizado com as regras descritas nesta secao; reabra o painel/conexao para recarregar o codigo. Em outros PCs, importe **ra_fild03.json** para aplicar o mesmo comportamento. Os arquivos de perfil do usuario nao sao substituidos automaticamente pelo exemplo.


### Aquisicao quando a area esta livre e Doki passivo

O perfil agora usa `engagement.seek_when_clear: true`. Alvos proximos ja envolvidos no combate continuam prioritarios; quando nao ha monstros proximos, escolhe um alvo visivel alcancavel dentro do raio de busca do painel e se aproxima. O alvo adquirido continua valido ao cruzar as nove celulas, sem esperar que ataque primeiro. Atacantes a distancia conhecidos tambem nao sao descartados somente por estarem fora das nove celulas. Monstros com ataque recente direcionado a outra pessoa ficam fora dessa aquisicao.

`engagement.proactive_species: [1177]` e a excecao do Doki: por ser passivo, pode ser escolhido sem ataque/conjuracao em voce. O bot continua exigindo silencio confirmado antes do primeiro dano e mantem as regras de controle/renovacao ja descritas. A regra de selecionar apenas quem mira voce nao se aplica ao Doki. Salamandra continua excluida da aquisicao por perseguicao.

A validacao de envio da patrulha agora consulta a mesma decisao do perfil. Antes, o planejador ignorava um monstro inelegivel, mas a validacao recusava o passo com "Alvo apareceu; patrulha interrompida", repetindo indefinidamente. O log de 20261106-030824-592136-painel mostrou essa repeticao contra a Ninkame 111902894, com o personagem em [121,252] e o alvo em [113,257], fora das nove celulas. Ha teste reproduzindo essas coordenadas e validando o envio da aproximacao.

Ao iniciar um combate, a primeira ofensiva ja em alcance e tentada antes de renovacoes opcionais de buff. Depois desse primeiro envio, a manutencao normal dos buffs volta a intercalar. Os bloqueios reais de SP, recarga, conjuracao e alcance continuam sendo respeitados.

### Nevoa toxica, Namekuji e emergencia de Jounin

O caminho de combate e de quest bloqueia celulas de habilidades hostis de terreno recebidas do servidor e revalida cada movimento antes do envio. Ao observar uma conjuracao com origem e celula explicitas, consulta os modelos de area do catalogo RCX e reserva essa area antes de a unidade aparecer. A antiga previsao da Venom Dust (140) da Salamandra (1831) tambem permanece. Quando a nuvem ou outra area prevista toca o personagem ou o trajeto atual, interrompe o movimento ou procura uma saida segura usando colisao do mapa. Sem caminho de fuga confirmado, nao envia um movimento cego.

Campos de suporte conhecidos, como Pneuma, Santuario e buffs elementais, nao sao considerados ameacas. Para uma habilidade sem modelo de area ou sem celula/origem identificavel, o bot nao inventa o raio: bloqueia somente as unidades/celulas efetivamente recebidas do servidor. A previsao so inclui conjuracoes de outros personagens; o bot nao foge do proprio efeito de terreno.

Namekuji (729) exige HP e HP maximo recentes informados pelo servidor, HP estritamente abaixo de 60% e nenhum monstro visivel no raio de 4 celulas. Se o servidor nao informou os valores de HP, nao invoca por seguranca. Com 4 ou mais Jounin (1634) no raio configurado de 9 celulas, a emergencia tem prioridade sobre buffs e ofensivas: Coelho (500) tres vezes confirmados, Fukai Kemuri (668) quando liberada pelo servidor e retirada ate os Jounin sairem da visibilidade recebida.
