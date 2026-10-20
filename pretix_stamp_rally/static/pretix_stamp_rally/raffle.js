(function () {
    var spinUrl = JSON.parse(document.getElementById("spin-url").textContent);
    var labels = document.getElementById("labels");
    var csrf = document.querySelector("[name=csrfmiddlewaretoken]").value;
    var prize = document.getElementById("prize");
    var pool = document.getElementById("pool");
    var spins = document.getElementById("spins");
    var button = document.getElementById("spin-btn");
    var reel = document.getElementById("reel");
    var windowEl = document.getElementById("window");
    var marquee = document.getElementById("marquee");
    var caption = document.getElementById("caption");
    var winners = document.getElementById("winners");
    var winnerList = document.getElementById("winner-list");
    var busy = false;
    var reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    function label(name) {
        return labels.getAttribute("data-" + name) || "";
    }

    function card(entry) {
        var node = document.createElement("div");
        node.className = "card";
        var name = document.createElement("div");
        name.className = "name";
        name.textContent = entry.name || "—";
        var order = document.createElement("div");
        order.className = "order";
        order.textContent = entry.order || "";
        node.appendChild(name);
        node.appendChild(order);
        return node;
    }

    function remember(winner, title) {
        winners.hidden = false;
        var item = document.createElement("li");
        var name = document.createElement("strong");
        name.textContent = winner.name || "—";
        var order = document.createElement("span");
        order.className = "order";
        order.textContent = winner.order || "";
        item.appendChild(name);
        item.appendChild(order);
        if (title) {
            var prizeNode = document.createElement("span");
            prizeNode.className = "prize";
            prizeNode.textContent = title;
            item.appendChild(prizeNode);
        }
        winnerList.insertBefore(item, winnerList.firstChild);
    }

    function showReel(entries, animate) {
        reel.textContent = "";
        entries.forEach(function (entry) {
            reel.appendChild(card(entry));
        });
        var cardHeight = reel.querySelector(".card").getBoundingClientRect().height;
        var distance = Math.max(0, (entries.length - 1) * cardHeight);
        reel.style.transition = "none";
        reel.style.transform = "translateY(0)";
        windowEl.classList.remove("winner");
        if (!animate || reduceMotion || distance === 0) {
            reel.style.transform = "translateY(-" + distance + "px)";
            windowEl.classList.add("winner");
            return Promise.resolve();
        }
        return new Promise(function (resolve) {
            var done = false;
            function finish() {
                if (done) {
                    return;
                }
                done = true;
                windowEl.classList.add("winner");
                resolve();
            }
            window.requestAnimationFrame(function () {
                window.requestAnimationFrame(function () {
                    reel.style.transition = "transform 4.6s cubic-bezier(.12, .75, .05, 1)";
                    reel.style.transform = "translateY(-" + distance + "px)";
                });
            });
            reel.addEventListener("transitionend", function (event) {
                if (event.target === reel && event.propertyName === "transform") {
                    finish();
                }
            }, {once: true});
            window.setTimeout(finish, 5200);
        });
    }

    function spinOnce() {
        return fetch(spinUrl, {
            method: "POST",
            credentials: "same-origin",
            headers: {
                "Content-Type": "application/json",
                "X-CSRFToken": csrf
            },
            body: JSON.stringify({
                title: prize.value,
                pool: pool.value
            })
        }).then(function (res) {
            return res.json().then(function (data) {
                data.http = res.status;
                return data;
            });
        }).then(function (data) {
            if (data.status !== "ok" || !data.reel || !data.reel.length) {
                throw new Error(data.message || label("error"));
            }
            marquee.textContent = data.title || label("winner");
            return showReel(data.reel, true).then(function () {
                caption.textContent = (data.winner.name || "") + " · " + (data.winner.order || "");
                remember(data.winner, data.title);
                return data;
            });
        });
    }

    function run(count, index) {
        marquee.textContent = label("winner") + " " + index + " / " + count;
        return spinOnce().then(function (data) {
            if (index >= count || !data.remaining) {
                return;
            }
            return new Promise(function (resolve) {
                window.setTimeout(resolve, reduceMotion ? 200 : 1400);
            }).then(function () {
                return run(count, index + 1);
            });
        });
    }

    button.addEventListener("click", function () {
        if (busy) {
            return;
        }
        var count = parseInt(spins.value, 10);
        if (!count || count < 1) {
            count = 1;
        }
        if (count > 30) {
            count = 30;
        }
        busy = true;
        button.disabled = true;
        prize.disabled = true;
        pool.disabled = true;
        spins.disabled = true;
        caption.textContent = "";
        run(count, 1).catch(function (error) {
            marquee.textContent = label("ready");
            caption.textContent = error.message || label("error");
            windowEl.classList.remove("winner");
        }).finally(function () {
            busy = false;
            button.disabled = false;
            prize.disabled = false;
            pool.disabled = false;
            spins.disabled = false;
            button.textContent = label("again");
        });
    });
})();
