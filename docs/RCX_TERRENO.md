# RCX / M2E no chao do NRO

O bot possui um renderer nativo proprio para o cliente NRO x86 validado. A aba **RCX ? Ativar RCX** liga a pintura cinza das celulas de habilidades diretamente no Direct3D do jogo. **Desativar RCX** remove o desenho sem reiniciar o jogo. Entre no personagem e aguarde carregar o mapa antes de ativar. A janela mostra se houve confirmacao real do renderer, quantas celulas foram recebidas e quantas foram desenhadas.

Para abrir esse controle sem fechar o painel/relay atual, execute `ABRIR_RCX.bat`. Ele acompanha a sessao local mais recente. Para receber a captura atualizada de todos os tipos de terreno, reabra o painel/conexao depois da atualizacao. Nao e necessario instalar o RCX antigo ou substituir dinput.dll.

## Celulas reais e cor

A captura acompanha as unidades visiveis de terreno recebidas nos pacotes 011F e suas remocoes 0120, com os tipos originais de Ragnarok de 0x7E a 0xFF. Isso inclui Proteger Terreno (0x9D), Santuario (0x83), barreiras, portais e outros efeitos que o cliente recebe como unidades de chao. IDs de unidade nao sao IDs de habilidades aprendidas nem opcodes. Nao se cria um quadrado a partir do alcance de conjuracao: sao desenhadas somente as coordenadas efetivamente recebidas. Unidades sobrepostas permanecem ate a ultima remocao daquela celula. Troca de mapa, desconexao e estado sem atualizacao limpam o desenho. Habilidades customizadas que usem outro tipo de efeito precisam de validacao especifica.

O desenho usa cinza #808080 opaco e borda #303030. Os quatro cantos seguem as alturas reais do terreno carregado e sao projetados pela matriz atual da camera, a cada quadro. O teste de profundidade e mantido para respeitar terreno e personagens. As celulas nao vao para o minimapa. A captura e limitada ao que o servidor informa ao proprio cliente, nao ao mapa inteiro.

## Compatibilidade e funcionamento

O layout foi conferido no NRO.exe original e na variante de camera/tremor identificados por SHA256 em nrobot/rcx_client.py. Outros executaveis sao recusados antes de instalar o renderer. A validacao confere dimensoes do terreno, matriz, parametros de projecao e dispositivo Direct3D7.

A DLL propria e carregada por um helper x86 do Windows e integra o SetRenderState do dispositivo existente. Ela nao envia pacotes, nao altera habilidades/cooldowns e nao modifica o NRO.exe ou DLLs existentes no disco. O MouseFreedom existente e preservado. Desativar interrompe o desenho; o modulo permanece carregado sem desenhar ate o jogo fechar, evitando descarregar callbacks ainda em uso. Sem atualizacao do painel, a pintura expira em ate 2,5 segundos. Apenas um painel pode controlar o RCX de cada cliente por vez.

Os binarios e manifesto estao em data/recursos/rcx. O codigo-fonte e a licenca do componente estao em nrobot/native; o script tools/build_rcx.py recompila com Zig 0.13 para x86 Windows. O usuario final nao precisa de compilador. O manifesto verifica a integridade da DLL antes de carrega-la.

## Validacao e referencias

A ligacao ao Direct3D e um bloco temporario de nove celulas cinza foram verificados visualmente na instancia real do NRO, alinhados a grade durante mudanca de camera. O bloco de diagnostico foi removido. Isso valida o desenho nativo; a confirmacao visual de uma conjuracao real de Proteger Terreno/Santuario ainda depende de observar essa habilidade no jogo.

A arquitetura e os layouts foram pesquisados no [SimpleROHook original](https://github.com/sekishi1259/SimpleROHook), especialmente DrawM2E, CView, C3dAttr e CRenderer. O renderer e proprio, separado do pacote antigo. A versao publica 2018-04-11 foi baixada apenas para inspecao em third_party/simplerohook, ignorado pela publicacao, e nao foi executada. O pacote antigo nao reconhece NRO.exe e possui layouts de outro cliente; ele nao e usado para ativar este recurso.


Atualiza??o de lat?ncia: eventos de terreno publicam um arquivo pequeno independente
(`rcx_terreno.json`) na pasta de registros da sess?o. Com RCX ativo, o painel verifica
essa fonte a cada 33 ms, sem aguardar os 700 ms da atualiza??o geral da interface.
A lat?ncia final tamb?m depende da chegada do pacote, da carga da interface e do
pr?ximo quadro renderizado pelo cliente. Trocas de mapa e fechamento limpam a fonte.

## Magias em area com unidade unica

Chuva de Meteoros, Nevasca, Lorde dos Kaos, Ira de Thor e Furia da Terra usam o mesmo tipo de
unidade (0x86 DUMMYSKILL), e o servidor pode enviar so a celula central. Quando o mesmo
conjurador anunciou a magia no chao (pacote 0x0117, ou 0x013E como reserva ao fim da barra de
conjuracao) numa celula compativel, o RCX desenha a area da magia enquanto a unidade existir:
Nevasca 9x9, Lorde dos Kaos 11x11 (nivel 11: 15x15), Ira de Thor e Furia da Terra 5x5 (Ira
nivel 11: 7x7), todas centradas na celula da magia; cada meteoro desenha 7x7 onde caiu.
Sem esse anuncio, a unidade continua como uma celula. Outros tipos de unidade (Protecao do
Terreno, Santuario etc.) nunca sao ampliados. Areas seguem rAthena pre-re; magias
customizadas do NRO podem precisar de ajuste em nrobot/ground_cells.py (AREA_SKILLS).
