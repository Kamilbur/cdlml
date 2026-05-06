#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include "cdlml.h"
#include <stdio.h>

static PyObject *py_cdlml_open(PyObject *Py_UNUSED(self), PyObject *args) {
    const char *filename = NULL;
    PyObject *name = NULL, *name2 = NULL;
    void *handle = NULL;

    if (!PyArg_ParseTuple(args, "O", &name)) {
        return NULL;
    }

    if (name != Py_None) {
        if (PyUnicode_FSConverter(name, &name2) == 0)
            return NULL;
        filename = PyBytes_AS_STRING(name2);
    } else {
        filename = NULL;
        name2 = NULL;
    }
    if (PySys_Audit("cdlml.dlmopen", "O", name) < 0) {
        return NULL;
    }
    dlerror();
    handle = cdlml_open(filename);
    Py_XDECREF(name2);
    if (!handle) {
        if (!cdlml_is_supported()) {
            PyErr_SetString(PyExc_OSError, "dlmopen unavailable on this platform");
            return NULL;
        }
        const char *errmsg = dlerror();
        if (errmsg) {
            PyErr_SetString(PyExc_OSError, errmsg);
            return NULL;
        }
        PyErr_SetString(PyExc_OSError, "dlmopen/dlinfo error");
        return NULL;
    }
    return PyLong_FromVoidPtr(handle);
}

static PyObject *py_cdlml_stop(PyObject *Py_UNUSED(self), PyObject *Py_UNUSED(args)) {
    cdlml_reset();
    Py_RETURN_NONE;
}

static PyObject *py_cdlml_is_available(PyObject *Py_UNUSED(self), PyObject *Py_UNUSED(args)) {
    if (cdlml_is_supported()) {
        Py_RETURN_TRUE;
    }
    Py_RETURN_FALSE;
}

static PyMethodDef Methods[] = {
    {"_dlmopen", py_cdlml_open, METH_VARARGS, "(implemented in C)"},
    {"_dlmstop", py_cdlml_stop, METH_NOARGS, "(implemented in C)"},
    {"_is_available", py_cdlml_is_available, METH_NOARGS, "(implemented in C)"},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef moduledef = {
    PyModuleDef_HEAD_INIT,
    "_cdlml",
    "CDLML module for dlmopen functionality in separete namespaces.",
    -1,
    Methods,
    NULL,
    NULL,
    NULL,
    NULL
};

PyMODINIT_FUNC PyInit__cdlml(void) {
    return PyModule_Create(&moduledef);
}
