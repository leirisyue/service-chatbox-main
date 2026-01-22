import { DialogActions, DialogContent, DialogContentText, TextField } from '@mui/material';
import Button from '@mui/material/Button';
import Dialog from '@mui/material/Dialog';
import DialogTitle from '@mui/material/DialogTitle';
import Typography from '@mui/material/Typography';
import { useAtom } from 'jotai/react';
import * as React from 'react';
import { emailUserAtom } from '../atom/variableAtom';

const emails = ['username@gmail.com', 'user02@gmail.com'];

export interface SimpleDialogProps {
  open: boolean;
  selectedValue: string;
  onClose: (value: string) => void;
}

export function SimpleDialog(props: SimpleDialogProps) {
  const { onClose, selectedValue, open } = props;

  const [_, setEmailUser] = useAtom(emailUserAtom);

  const handleClose: DialogProps["onClose"] = (event, reason) => {
    if (reason && reason === "backdropClick")
      return;
    onClose(selectedValue);
  };

  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    const formJson = Object.fromEntries((formData).entries());
    const email = formJson?.email;
    setEmailUser(email);
    console.log(email);
    handleClose();
  };

  return (
    <Dialog open={open} onClose={handleClose} onBackdropClick="false" >
      <DialogTitle>Đăng nhập</DialogTitle>
      <DialogContent>
        <DialogContentText>
          Hãy nhập Email để có thể lưu trữ lịch sử trò chuyện của bạn.
          <br />
          <Typography color='success'><small>(Bạn có thể bỏ qua nếu không muốn xem lại lịch sử trò chuyện)</small></Typography>
        </DialogContentText>
        <br />
        <form onSubmit={handleSubmit} id="subscription-form">
          <TextField
            autoFocus
            required
            margin="dense"
            id="name"
            name="email"
            label="Địa chỉ Email"
            type="email"
            fullWidth
            variant="standard"
          />
        </form>
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose}>Cancel</Button>
        <Button type="submit" form="subscription-form">
          Submit
        </Button>
      </DialogActions>
    </Dialog>
  );
}


export default function ModalEmailUser() {
  const [open, setOpen] = React.useState(false);
  const [selectedValue, setSelectedValue] = React.useState(emails[1]);
  const handleClickOpen = () => {
    setOpen(true);
  };
  const handleClose = (value: string) => {
    setOpen(false);
    setSelectedValue(value);
  };
  return (
    <div>
      <Typography variant="subtitle1" component="div">
        Selected: {selectedValue}
      </Typography>
      <br />
      <Button variant="outlined" onClick={handleClickOpen}>
        Open simple dialog
      </Button>
      <SimpleDialog
        selectedValue={selectedValue}
        open={open}
        onClose={handleClose}
      />
    </div>
  );
}