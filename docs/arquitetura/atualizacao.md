# O aviso de versão nova e a atualização (`atualizacao.py`)

`atualizacao.py`: o aviso de versão nova e a atualização pelo instalador (o caminho A do
atualizador). O app baixa o manifesto das versões e a assinatura dele, e só
aceita o que a chave pública Ed25519 embutida no módulo assinou, e só para uma versão mais nova
que a dele (um manifesto velho não volta a versão). O setup.exe novo vem com o tamanho e o hash
conferidos e roda em modo silencioso, com o pedido de permissão do Windows: o instalador fecha
o Ritmelli, troca a pasta dele e abre de novo. Os downloads ficam em
`%LOCALAPPDATA%\Ritmelli\atualizacao`. Enquanto o endereço do manifesto e a chave estão vazios, e
sempre que roda pelo código, nada é consultado. Teste: `python dev/testa_atualizacao.py`.
