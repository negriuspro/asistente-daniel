package com.jarvis.app

import android.Manifest
import android.annotation.SuppressLint
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.view.View
import android.view.WindowManager
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat

class MainActivity : AppCompatActivity(), RecognitionListener {

    private lateinit var webView: WebView
    private var speechRecognizer: SpeechRecognizer? = null
    private val handler = Handler(Looper.getMainLooper())

    // ← IP de tu PC en la red WiFi
    private val SERVER_URL = "http://192.168.100.52:8000"

    private val PERMS     = arrayOf(Manifest.permission.RECORD_AUDIO)
    private val PERM_CODE = 1001

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        hideSystemUI()
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)

        webView = WebView(this)
        webView.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
        }

        webView.webViewClient = object : WebViewClient() {

            override fun onPageFinished(view: WebView, url: String) {
                /* Avisa al JS que usamos STT nativo — saltar Web Speech API */
                view.evaluateJavascript("window.ANDROID_NATIVE = true;", null)
            }

            /* Versión compatible con API 19+ */
            @Suppress("OverridingDeprecatedMember", "DEPRECATION")
            override fun onReceivedError(
                view: WebView, errorCode: Int, description: String, failingUrl: String
            ) {
                view.postDelayed({ view.loadUrl(SERVER_URL) }, 3_000)
            }
        }

        setContentView(webView)
        webView.loadUrl(SERVER_URL)

        if (hasPermissions()) initSpeech()
        else ActivityCompat.requestPermissions(this, PERMS, PERM_CODE)
    }

    /* ── STT nativo Android ─────────────────────────────────────────── */

    private fun initSpeech() {
        if (!SpeechRecognizer.isRecognitionAvailable(this)) return
        speechRecognizer = SpeechRecognizer.createSpeechRecognizer(this)
        speechRecognizer?.setRecognitionListener(this)
        startListening()
    }

    private fun startListening() {
        val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL,
                     RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            putExtra(RecognizerIntent.EXTRA_LANGUAGE,            "es-ES")
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_PREFERENCE, "es-ES")
            putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS,     true)
            putExtra(RecognizerIntent.EXTRA_MAX_RESULTS,         1)
        }
        try {
            speechRecognizer?.startListening(intent)
        } catch (_: Exception) {
            handler.postDelayed(::startListening, 1_000)
        }
    }

    /* ── RecognitionListener ────────────────────────────────────────── */

    override fun onPartialResults(partialResults: Bundle) {
        val text = partialResults
            .getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
            ?.firstOrNull() ?: return
        inject(text, false)
    }

    override fun onResults(results: Bundle) {
        val text = results
            .getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
            ?.firstOrNull() ?: ""
        if (text.isNotBlank()) inject(text, true)
        handler.postDelayed(::startListening, 400)
    }

    override fun onError(error: Int) {
        val delay = if (error == SpeechRecognizer.ERROR_RECOGNIZER_BUSY) 1_200L else 500L
        handler.postDelayed(::startListening, delay)
    }

    override fun onReadyForSpeech(params: Bundle?)    {}
    override fun onBeginningOfSpeech()                {}
    override fun onRmsChanged(rmsdB: Float)           {}
    override fun onBufferReceived(buffer: ByteArray?) {}
    override fun onEndOfSpeech()                      {}
    override fun onEvent(eventType: Int, params: Bundle?) {}

    /* ── Helpers ────────────────────────────────────────────────────── */

    private fun inject(text: String, isFinal: Boolean) {
        val safe = text.replace("\\", "\\\\").replace("'", "\\'")
        webView.evaluateJavascript("window.onNativeResult('$safe',$isFinal)", null)
    }

    private fun hasPermissions() = PERMS.all {
        ContextCompat.checkSelfPermission(this, it) == PackageManager.PERMISSION_GRANTED
    }

    override fun onRequestPermissionsResult(
        code: Int, perms: Array<String>, results: IntArray
    ) {
        super.onRequestPermissionsResult(code, perms, results)
        if (code == PERM_CODE) initSpeech()
    }

    @Suppress("DEPRECATION")
    override fun onBackPressed() {
        if (webView.canGoBack()) webView.goBack()
    }

    override fun onDestroy() {
        super.onDestroy()
        speechRecognizer?.destroy()
    }

    @Suppress("DEPRECATION")
    private fun hideSystemUI() {
        window.decorView.systemUiVisibility = (
            View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
            or View.SYSTEM_UI_FLAG_FULLSCREEN
            or View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
            or View.SYSTEM_UI_FLAG_LAYOUT_STABLE
            or View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
            or View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
        )
    }

    @Suppress("DEPRECATION")
    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus) hideSystemUI()
    }
}
