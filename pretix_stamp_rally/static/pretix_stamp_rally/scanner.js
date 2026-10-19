(function () {
    var form = document.getElementById("scan-form");
    var input = document.getElementById("code");
    var statusBox = document.getElementById("status");
    var cameraBtn = document.getElementById("camera-btn");
    var video = document.getElementById("preview");
    var scanUrlEl = document.getElementById("scan-url");
    var scanUrl = scanUrlEl ? JSON.parse(scanUrlEl.textContent) : form.action;
    var csrf = form.querySelector("[name=csrfmiddlewaretoken]").value;
    var busy = false;
    var stream = null;
    var detectTimer = null;

    function setStatus(kind, message, meta) {
        statusBox.className = kind || "";
        statusBox.querySelector(".msg").textContent = message;
        statusBox.querySelector(".meta").textContent = meta || "";
    }

    function submitCode(code) {
        if (busy || !code) {
            return;
        }
        busy = true;
        setStatus("", "Scanning…", "");
        fetch(scanUrl, {
            method: "POST",
            credentials: "same-origin",
            headers: {
                "Content-Type": "application/json",
                "X-CSRFToken": csrf
            },
            body: JSON.stringify({code: code})
        }).then(function (res) {
            return res.json().then(function (data) {
                data.http = res.status;
                return data;
            });
        }).then(function (data) {
            var kind = "error";
            if (data.status === "ok" && data.complete) {
                kind = "complete";
            } else if (data.status === "ok") {
                kind = "ok";
            } else if (data.status === "duplicate") {
                kind = "duplicate";
            }
            var meta = [];
            if (data.attendee) {
                meta.push(data.attendee);
            }
            if (data.order) {
                meta.push(data.order);
            }
            if (data.required) {
                meta.push((data.collected || 0) + "/" + data.required);
            }
            setStatus(kind, data.message || "Unknown response", meta.join(" · "));
        }).catch(function () {
            setStatus("error", "Could not reach the server.", "");
        }).finally(function () {
            busy = false;
            input.value = "";
            input.focus();
        });
    }

    form.addEventListener("submit", function (ev) {
        ev.preventDefault();
        submitCode(input.value.trim());
    });

    function stopCamera() {
        if (detectTimer) {
            window.clearInterval(detectTimer);
            detectTimer = null;
        }
        if (stream) {
            stream.getTracks().forEach(function (t) { t.stop(); });
            stream = null;
        }
        video.classList.remove("active");
        cameraBtn.textContent = cameraBtn.getAttribute("data-label-start") || "Use camera";
    }

    function startDetectLoop() {
        if (!window.BarcodeDetector) {
            setStatus("error", "This browser cannot decode QR codes from the camera. Type or use a hardware scanner.", "");
            return;
        }
        var detector = new BarcodeDetector({formats: ["qr_code", "code_128", "code_39", "aztec", "pdf417"]});
        detectTimer = window.setInterval(function () {
            if (busy || video.readyState < 2) {
                return;
            }
            detector.detect(video).then(function (barcodes) {
                if (barcodes && barcodes.length) {
                    submitCode(barcodes[0].rawValue);
                }
            }).catch(function () {});
        }, 400);
    }

    cameraBtn.addEventListener("click", function () {
        if (stream) {
            stopCamera();
            return;
        }
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            setStatus("error", "Camera access is not available.", "");
            return;
        }
        navigator.mediaDevices.getUserMedia({video: {facingMode: "environment"}}).then(function (mediaStream) {
            stream = mediaStream;
            video.srcObject = stream;
            video.classList.add("active");
            video.play();
            cameraBtn.setAttribute("data-label-start", cameraBtn.textContent);
            cameraBtn.textContent = "Stop camera";
            startDetectLoop();
        }).catch(function () {
            setStatus("error", "Could not start the camera.", "");
        });
    });
})();
