import React from 'react';
import { Box, Button, Card, CardContent, Chip, Typography } from '@material-ui/core';
import { makeStyles } from '@material-ui/styles';
import CheckCircleOutlineIcon from '@material-ui/icons/CheckCircleOutline';
import ErrorOutlineIcon from '@material-ui/icons/ErrorOutline';
import WarningIcon from '@material-ui/icons/Warning';
import GetAppIcon from '@material-ui/icons/GetApp';

const useStyles = makeStyles((theme) => ({
    icon: { fontSize: '3rem', marginBottom: '8px' },
    successIcon: { color: theme.palette.success.main },
    warningIcon: { color: theme.palette.warning.main },
    errorIcon:   { color: theme.palette.error.main },
    row: {
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        padding: '8px 0',
    },
}));

/**
 * Download a base64-encoded xlsx blob as a file.
 */
export function downloadErrorExcel(base64Data, filename) {
    const bytes = Uint8Array.from(atob(base64Data), c => c.charCodeAt(0));
    const blob = new Blob([bytes], {
        type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

/**
 * Reusable upload result card.
 *
 * Props:
 *   result          – API response: { success, processed_count, error_count, error_report?, ...extra }
 *   onReset         – () => void   called when the user clicks "Upload Another" / "Try Again"
 *   successLabel    – string       e.g. "Orders Processed" / "Invoices Processed"
 *   errorFilename   – string       filename for the downloaded error Excel
 *   extraStats      – [{ label, value, color }]  optional extra chips below the main count
 */
const UploadResultCard = ({ result, onReset, successLabel, errorFilename, extraStats = [] }) => {
    const classes = useStyles();

    if (!result) return null;

    const { success, processed_count, error_count, error_report } = result;
    const hasErrors     = error_count > 0;
    const hasErrorReport = error_count > 1 && !!error_report;

    let Icon, iconClass, title;
    if (!success) {
        Icon = ErrorOutlineIcon; iconClass = classes.errorIcon;
        title = 'Processing Failed';
    } else if (hasErrors) {
        Icon = WarningIcon; iconClass = classes.warningIcon;
        title = 'Completed with Errors';
    } else {
        Icon = CheckCircleOutlineIcon; iconClass = classes.successIcon;
        title = 'Processing Successful!';
    }

    return (
        <Card style={{ marginTop: '16px' }}>
            <CardContent>
                <div style={{ textAlign: 'center', marginBottom: '16px' }}>
                    <Icon className={`${classes.icon} ${iconClass}`} />
                    <Typography variant="h6">{title}</Typography>
                </div>

                <div className={classes.row}>
                    <Typography variant="body1"><strong>{successLabel}:</strong></Typography>
                    <Chip label={processed_count} color="primary" />
                </div>

                {extraStats.map(({ label, value, color }) => (
                    <div key={label} className={classes.row}>
                        <Typography variant="body1"><strong>{label}:</strong></Typography>
                        <Chip label={value} color={color || 'default'} />
                    </div>
                ))}

                {hasErrors && (
                    <div className={classes.row}>
                        <Typography variant="body1"><strong>Failed Rows:</strong></Typography>
                        <Chip label={error_count} color="error" />
                    </div>
                )}

                <Box style={{ marginTop: '16px', display: 'flex', gap: '8px', justifyContent: 'center', flexWrap: 'wrap' }}>
                    <Button variant="outlined" color="primary" onClick={onReset}>
                        {success ? 'Upload Another File' : 'Try Again'}
                    </Button>

                    {hasErrorReport && (
                        <Button
                            variant="contained"
                            color="secondary"
                            startIcon={<GetAppIcon />}
                            onClick={() => downloadErrorExcel(error_report, errorFilename)}
                        >
                            Download Error Report
                        </Button>
                    )}
                </Box>
            </CardContent>
        </Card>
    );
};

export default UploadResultCard;
