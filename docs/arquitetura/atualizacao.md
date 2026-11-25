# O aviso de versão nova e a atualização (`atualizacao.py`)

`atualizacao.py`: o aviso de versão nova e a atualização pelo instalador (o caminho A do
atualizador). O app baixa o manifesto das versões e a assinatura dele, e só
aceita o que a chave pública Ed25519 embutida no módulo assinou, e só para uma versão mais nova
que a dele (um manifesto velho não volta a versão). O setup.exe novo vem com o tamanho e o hash
conferidos e roda em modo silencioso, com o pedido de permissão do Windows: o instalador fecha
o Ritmelli, troca a pasta dele e abre de novo. Os downloads ficam em
`%LOCALAPPDATA%\Ritmelli\atualizacao`. Enquanto o endereço do manifesto e a chave estão vazios, e
sempre que roda pelo código, nada é consultado. A parcial só serve numa pasta do app protegida
(`atualizacao.PROTEGIDA`, a regra do `pastas.pasta_protegida`); fora dela vai o setup completo, que
confere o destino. A tarefa de atualização (`atualizador.py`, a que roda como SYSTEM) confere a
mesma regra antes de gravar na pasta do app e, reprovada, apaga as duas tarefas que rodam como SYSTEM
(a do filtro e a dela, por último e sem o `/end`) e sai sem baixar nem rodar nada; só o setup
completo as cria de novo. A parcial só sai de uma versão anterior que já tem a sentinela
`_internal\pasta-protegida.txt` (`instalador/atualizacao/parcial.py`): as versões de antes da regra
caem no setup completo. Teste: `python dev/testa_atualizacao.py`, `python dev/testa_atualizador.py`
e `python instalador/atualizacao/testa_parcial.py`.
