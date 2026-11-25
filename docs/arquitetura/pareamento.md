# O celular pareado (`pareamento.py`)

`pareamento.py`: o celular pareado. O instalador libera a entrada no firewall também em
rede pública, e sem senha qualquer aparelho do mesmo Wi-Fi tocava no microfone do jogo e
baixava do YouTube. O PC é quem fala pelo `127.0.0.1` (pelo endereço de quem conectou, não
pelo Host, que quem pede escreve como quiser) e usa tudo; da rede, a API só responde com a
chave de um celular pareado. O botão Celular mostra um código de 6 números e um QR (do
`segno`) com o link que já leva o código. O código vale 5 min e uma vez só, e morre com 5
tentativas erradas, quando só o PC gera outro: sem isso, quem estivesse na rede podia
tentar até acertar. Pareado, o celular guarda a chave num cookie até o PC desconectar; o
`celulares.json` (na pasta de dados) guarda só o hash dela; estragado, ele não impede o app
de abrir, e os celulares pareiam de novo. O cookie vale para o IP do PC: se o roteador der
outro IP ao PC, o celular pareia de novo. Sem HTTPS (um certificado próprio faria o celular
avisar "não seguro"): numa Wi-Fi aberta, quem estiver na rede pode copiar o código ou o
cookie no ar, então é para a rede de casa.
