# BackdropCarousel customizations (Docker/CUSTOMIZATIONS.md "BackdropCarousel").
BDD=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../BackdropCarousel" && pwd)
if want backdrop-carousel; then
  check bd.rust '^/backdrop-carousel healthy$' "$(echo "$(docker inspect -f '{{join .Config.Entrypoint " "}}' backdrop-carousel) $(docker inspect -f '{{.State.Health.Status}}' backdrop-carousel)")"
  check bd.photos '^same [1-9][0-9]*$' "$(n=$(find "$BDD/photos" -maxdepth 1 -type f -regextype posix-extended -iregex '.*\.(jpe?g|png|webp|bmp|gif)$' | wc -l); l=$(curl -sk -m 10 --resolve backdrop-carousel.holy-grail.ch:443:192.168.1.2 https://backdrop-carousel.holy-grail.ch/ | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))' 2>&1); [[ $n == "$l" ]] && echo "same $n" || echo "files $n listed $l")"
  check bd.route '^200 image/(jpeg|png|webp|bmp|gif)$' "$(curl -sk -m 15 -o /dev/null -w '%{http_code} %{content_type}' --resolve backdrop-carousel.holy-grail.ch:443:192.168.1.2 https://backdrop-carousel.holy-grail.ch/random)"
fi
